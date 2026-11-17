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

from .registry import RegistryError
from .registry_editor import MAX_BYTES, RegistryConflict, open_registry, save_registry, validate_registry
from .runtime import prepare, project_info, select_plan, stop

ASSETS = Path(__file__).resolve().parent / "web"


class LoopbackHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # The numeric loopback address needs no reverse DNS lookup.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Control:
    def __init__(self, project):
        self.project = str(Path(project).resolve())
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.job = {"status": "idle", "events": []}

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.job))

    def edit_registry(self, action, body):
        project = body.get("project")
        if not isinstance(project, str) or not project.strip():
            raise RegistryError("project path is required")
        if action == "open":
            return open_registry(project)
        text = body.get("text")
        if not isinstance(text, str):
            raise RegistryError("registry text is required")
        if action == "validate":
            return validate_registry(project, text)
        revision = body.get("revision")
        if not isinstance(revision, str):
            raise RegistryError("open the registry before saving")
        with self.lock:
            if self.job["status"] == "running":
                raise RegistryConflict("wait for the running job before saving")
            return save_registry(project, text, revision)

    def start(self, action, body):
        project = body.get("project", self.project)
        if not isinstance(project, str) or not project:
            raise RegistryError("project path is required")
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
                    result = prepare(project, body["target"], profile=body["profile"], emit=emit)
                else:
                    result = stop(project, emit)
                with self.lock:
                    self.job.update(status="succeeded", result=result)
            except Exception as error:
                with self.lock:
                    self.job.update(status="failed", error=str(error) if isinstance(error, RegistryError)
                                    else "Local operation failed. Check project files and runtime availability.")

        threading.Thread(target=run, daemon=True).start()


def make_server(project, port=18770):
    control = Control(project)

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
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            try:
                if url.path == "/api/info":
                    return self.respond(200, {"project": control.project, "token": control.token,
                                              "injectorRoot": str(ASSETS.parent.parent)})
                if url.path == "/api/job":
                    return self.respond(200, control.snapshot())
                if url.path == "/api/project":
                    return self.respond(200, project_info(query.get("project", [control.project])[0]))
                if url.path == "/api/plan":
                    _, plan = select_plan(query["project"][0], query["target"][0], query["profile"][0])
                    return self.respond(200, plan)
                assets = {"/": ("index.html", "text/html; charset=utf-8"),
                          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                          "/style.css": ("style.css", "text/css; charset=utf-8")}
                if url.path in assets:
                    name, content_type = assets[url.path]
                    return self.respond(200, (ASSETS / name).read_bytes(), content_type)
                self.respond(404, {"error": "not found"})
            except (RegistryError, KeyError) as error:
                self.respond(400, {"error": str(error) if isinstance(error, RegistryError) else "missing query parameter"})

        def do_POST(self):
            if not self.allowed(mutation=True):
                return
            editor = self.path in ("/api/registry/open", "/api/registry/validate", "/api/registry/save")
            if not editor and self.path not in ("/api/prepare", "/api/stop"):
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


def serve(project, port=18770, open_browser=False):
    if open_browser and port:
        url = f"http://127.0.0.1:{port}"
        try:
            with build_opener(ProxyHandler({})).open(url + "/api/info", timeout=1) as response:
                info = json.load(response)
            if info.get("injectorRoot") == str(ASSETS.parent.parent):
                webbrowser.open(url)
                return
        except (OSError, ValueError):
            pass
    server = make_server(project, port)
    url = f"http://127.0.0.1:{server.server_port}"
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
