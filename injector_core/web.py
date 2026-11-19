"""Loopback-only control surface for the same runtime used by the CLI."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
from socketserver import TCPServer
import threading
from urllib.parse import parse_qs, urlsplit
from urllib.request import ProxyHandler, build_opener
import webbrowser

from .folder_picker import choose_project_folder, choose_registry_file
from .registry import RegistryError
from .registry_editor import MAX_BYTES, RegistryConflict, open_registry, save_registry, validate_registry
from .runtime import parse_variants, prepare, project_info, select_plan, stop

ASSETS = Path(__file__).resolve().parent / "web"
REGISTRIES = ASSETS.parent.parent / "registries"


def _registry_directory(value):
    if not value.strip():
        return None
    path = Path(value.strip())
    if path.name == "registry.json" and not path.is_dir():
        return str(path.parent)
    return str(path)


class LoopbackHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # The numeric loopback address needs no reverse DNS lookup.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Control:
    def __init__(self, project, registry=None):
        self.project = str(Path(project).resolve())
        self.registry = str(Path(registry).resolve()) if registry is not None else ""
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.picker_lock = threading.Lock()
        self.job = {"status": "idle", "events": []}

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.job))

    def pick_project(self, body):
        initial = body.get("project", "")
        if not isinstance(initial, str):
            raise RegistryError("project path must be a string")
        kind = body.get("kind", "project")
        if kind not in ("project", "registry"):
            raise RegistryError("unknown picker kind")
        if not self.picker_lock.acquire(blocking=False):
            raise RegistryConflict("선택 창이 이미 열려 있습니다.")
        try:
            default = self.project
            if kind == "registry":
                default = self.registry or str(REGISTRIES if REGISTRIES.is_dir() else REGISTRIES.parent)
            picker = choose_registry_file if kind == "registry" else choose_project_folder
            selected = picker(initial.strip() or default)
            if selected is None:
                return {"project": None}
            if kind == "registry":
                file = Path(selected)
                if file.name != "registry.json" or not file.is_file() or file.is_symlink():
                    raise RegistryError("registry.json 파일을 선택하세요.")
                return {"project": str(file.parent.resolve())}
            folder = Path(selected).resolve()
            if not folder.is_dir():
                raise RegistryError("기존 폴더를 선택하세요.")
            return {"project": str(folder)}
        finally:
            self.picker_lock.release()

    def registry_for(self, body):
        registry = body.get("registry", self.registry)
        if not isinstance(registry, str):
            raise RegistryError("registry path must be a string")
        return _registry_directory(registry)

    def edit_registry(self, action, body):
        project = body.get("project")
        if not isinstance(project, str) or not project.strip():
            raise RegistryError("project path is required")
        filename = body.get("file")
        if filename is not None and not isinstance(filename, str):
            raise RegistryError("registry file must be a string")
        registry = self.registry_for(body)
        if action == "open":
            return open_registry(project, filename, registry=registry)
        text = body.get("text")
        if not isinstance(text, str):
            raise RegistryError("registry text is required")
        if action == "validate":
            return validate_registry(project, text, filename, registry=registry)
        revision = body.get("revision")
        if not isinstance(revision, str):
            raise RegistryError("open the registry before saving")
        with self.lock:
            if self.job["status"] == "running":
                raise RegistryConflict("wait for the running job before saving")
            return save_registry(project, text, revision, filename, registry=registry)

    def start(self, action, body):
        project = body.get("project", self.project)
        if not isinstance(project, str) or not project:
            raise RegistryError("project path is required")
        registry = self.registry_for(body)
        if action == "prepare" and not all(isinstance(body.get(key), str) for key in ("target", "profile")):
            raise RegistryError("target and profile are required")
        with self.lock:
            if self.job["status"] == "running":
                raise RegistryError("a job is already running")
            self.job = {"status": "running", "action": action, "events": []}

        def emit(event):
            with self.lock:
                self.job["events"].append(event)

        def run():
            try:
                if action == "prepare":
                    result = prepare(project, body["target"], profile=body["profile"], emit=emit,
                                     variants=body.get("variants"), registry=registry)
                else:
                    result = stop(project, emit, registry=registry)
                with self.lock:
                    self.job.update(status="succeeded", result=result)
            except Exception as error:
                with self.lock:
                    self.job.update(status="failed", error=str(error) if isinstance(error, RegistryError)
                                    else "Local operation failed. Check project files and runtime availability.")

        threading.Thread(target=run, daemon=True).start()


def make_server(project, port=18770, *, registry=None):
    control = Control(project, registry)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, body, content_type="application/json; charset=utf-8"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self, mutation=False):
            port = self.server.server_port
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            host = self.headers.get("Host")
            if host not in hosts:
                self.respond(403, {"error": "local host required"})
                return False
            if mutation and (self.headers.get("Origin") not in {None, f"http://{host}"}
                             or not secrets.compare_digest(self.headers.get("X-Injector-Token", ""), control.token)):
                self.respond(403, {"error": "local control token required"})
                return False
            return True

        def do_GET(self):
            if not self.allowed():
                return
            try:
                url = urlsplit(self.path)
                query = parse_qs(url.query, keep_blank_values=True)
                registry = _registry_directory(query.get("registry", [control.registry])[0])
                if url.path == "/api/info":
                    registries = (sorted(str(path) for path in REGISTRIES.iterdir()
                                         if (path / "registry.json").is_file()) if REGISTRIES.is_dir() else [])
                    return self.respond(200, {"project": control.project, "registry": control.registry,
                                              "registries": registries, "token": control.token,
                                              "injectorRoot": str(ASSETS.parent.parent)})
                if url.path == "/api/job":
                    return self.respond(200, control.snapshot())
                if url.path == "/api/project":
                    return self.respond(200, project_info(query.get("project", [control.project])[0], registry=registry))
                if url.path in ("/api/plan", "/api/graph"):
                    target = query["target"][0] if url.path == "/api/plan" else query.get("target", [None])[0]
                    variants = parse_variants(query.get("variant", []))
                    _, plan = select_plan(query["project"][0], target, query["profile"][0], variants=variants, registry=registry)
                    return self.respond(200, plan)
                assets = {"/": ("index.html", "text/html; charset=utf-8"),
                          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                          "/graph.js": ("graph.js", "text/javascript; charset=utf-8"),
                          "/style.css": ("style.css", "text/css; charset=utf-8")}
                if url.path in assets:
                    name, content_type = assets[url.path]
                    return self.respond(200, (ASSETS / name).read_bytes(), content_type)
                self.respond(404, {"error": "not found"})
            except (RegistryError, KeyError) as error:
                self.respond(400, {"error": str(error) if isinstance(error, RegistryError) else "missing query parameter"})
            except (ValueError, OSError, RecursionError):
                self.respond(400, {"error": "cannot read project registry or request path"})

        def do_POST(self):
            if not self.allowed(mutation=True):
                return
            editor = self.path in ("/api/registry/open", "/api/registry/validate", "/api/registry/save")
            if not editor and self.path not in ("/api/project/pick", "/api/prepare", "/api/stop"):
                return self.respond(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                limit = 6 * MAX_BYTES + 16384 if editor else 16384
                if length <= 0 or length > limit:
                    raise ValueError()
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError()
                action = self.path.rsplit("/", 1)[1]
                if action == "pick":
                    return self.respond(200, control.pick_project(body))
                if editor:
                    return self.respond(200, control.edit_registry(action, body))
                control.start(action, body)
                self.respond(202, {"status": "running"})
            except RegistryConflict as error:
                self.respond(409, {"error": str(error)})
            except RegistryError as error:
                self.respond(400, {"error": str(error)})
            except UnicodeError:
                self.respond(400, {"error": "registry.json must be UTF-8"})
            except (ValueError, RecursionError):
                self.respond(400, {"error": "invalid request or registry text"})
            except OSError:
                self.respond(400, {"error": "cannot read or save project registry.json"})

    return LoopbackHTTPServer(("127.0.0.1", port), Handler)


def serve(project, port=18770, open_browser=False, *, registry=None):
    if open_browser and port:
        url = f"http://127.0.0.1:{port}"
        try:
            with build_opener(ProxyHandler({})).open(url + "/api/info", timeout=1) as response:
                info = json.load(response)
            if info.get("injectorRoot") == str(ASSETS.parent.parent):
                if registry is not None and (info.get("project"), info.get("registry")) != (
                        str(Path(project).resolve()), str(Path(registry).resolve())):
                    raise RegistryError("Injector is already running on this port; select the folders in the browser or use another --port")
                webbrowser.open(url)
                return
        except (OSError, ValueError):
            pass
    server = make_server(project, port, registry=registry)
    url = f"http://127.0.0.1:{server.server_port}"
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
