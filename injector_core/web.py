"""Loopback-only control surface for the same runtime used by the CLI."""
import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import secrets
import threading
from urllib.parse import parse_qs, urlsplit
from urllib.request import ProxyHandler, build_opener
import webbrowser

from .folder_picker import choose_project_folder, choose_registry_file, choose_suite_file
from .loopback import LoopbackHTTPServer
from .observation_contract import MAX_OBSERVATION_BYTES, decode_document
from .registry import RegistryError, _parse_json, registry_path
from .registry_editor import MAX_BYTES, RegistryConflict, open_registry, save_registry, validate_registry
from .rendering import _artifact_path, _replace_file
from .runtime import check_requirements, parse_variants, prepare, project_info, select_plan, stop

ASSETS = Path(__file__).resolve().parent / "web"
REGISTRIES = ASSETS.parent.parent / "registries"
WEB_SELECTION = ASSETS.parent.parent / ".local" / "web-selection.json"
VERIFICATION_RUNS = ASSETS.parent.parent / ".local" / "verification"


class Control:
    def __init__(self, project, registry, selection_file, restore_selection):
        self.selection = {"project": str(Path(project).resolve()),
                          "registry": str(registry_path(project, registry)) if registry is not None else ""}
        self.selection_file = selection_file
        if selection_file is not None and restore_selection:
            try:
                _artifact_path(selection_file.parent.parent, selection_file)
                saved = json.loads(selection_file.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    source, settings = saved.get("project"), saved.get("registry")
                    if (isinstance(source, str) and Path(source).is_absolute() and "\x00" not in source
                            and isinstance(settings, str) and "\x00" not in settings
                            and (not settings or Path(settings).is_absolute())):
                        self.selection = {"project": source, "registry": settings}
            except (OSError, ValueError, RuntimeError):
                pass
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.picker_lock = threading.Lock()
        self.job = {"status": "idle", "events": []}

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.job))

    def load_project(self, body):
        project = body.get("project")
        if not isinstance(project, str) or not project.strip():
            raise RegistryError("project path is required")
        result = project_info(project, registry=self.registry_for(body))
        with self.lock:
            self.selection = {key: result[key] for key in ("project", "registry")}
            if self.selection_file is not None:
                try:
                    _artifact_path(self.selection_file.parent.parent, self.selection_file)
                    _replace_file(self.selection_file, json.dumps(self.selection, ensure_ascii=False).encode("utf-8"))
                except (OSError, ValueError, RuntimeError):
                    result["remembered"] = False
        return result

    def pick_project(self, body):
        initial = body.get("project", "")
        if not isinstance(initial, str):
            raise RegistryError("project path must be a string")
        kind = body.get("kind", "project")
        if kind not in ("project", "registry", "suite"):
            raise RegistryError("unknown picker kind")
        if not self.picker_lock.acquire(blocking=False):
            raise RegistryConflict("선택 창이 이미 열려 있습니다.")
        try:
            default = self.selection["project"]
            if kind == "registry":
                default = self.selection["registry"] or str(REGISTRIES if REGISTRIES.is_dir() else REGISTRIES.parent)
            picker = {"project": choose_project_folder, "registry": choose_registry_file, "suite": choose_suite_file}[kind]
            selected = picker(initial.strip() or default)
            if selected is None:
                return {"project": None}
            if kind != "project":
                file = Path(selected)
                if not file.is_file() or file.is_symlink():
                    raise RegistryError("기존 파일을 선택하세요.")
                return {"project": str(file.resolve())}
            folder = Path(selected).resolve()
            if not folder.is_dir():
                raise RegistryError("기존 폴더를 선택하세요.")
            return {"project": str(folder)}
        finally:
            self.picker_lock.release()

    def registry_for(self, body):
        registry = body.get("registry", self.selection["registry"])
        if not isinstance(registry, str):
            raise RegistryError("registry path must be a string")
        return registry.strip() or None

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

    def suite_inputs(self, body):
        keys = ("suite", "project", "candidate")
        if not all(isinstance(body.get(key), str) and body[key].strip() and "\x00" not in body[key] for key in keys):
            raise RegistryError("스위트 파일과 기준·후보 워크트리 경로를 입력하세요.")
        return tuple(Path(body[key]).resolve() for key in keys)

    def start(self, action, body):
        project = body.get("project", self.selection["project"])
        if not isinstance(project, str) or not project:
            raise RegistryError("project path is required")
        registry = self.registry_for(body)
        if action == "prepare" and not all(isinstance(body.get(key), str) for key in ("target", "profile")):
            raise RegistryError("target and profile are required")
        if action == "suite":
            suite_inputs = self.suite_inputs(body)
            destination = VERIFICATION_RUNS / secrets.token_hex(8)
            _artifact_path(ASSETS.parent.parent, destination / "report.json")
        context = {"project": str(Path(project).resolve()), "registry": str(registry or "")}
        if action == "prepare":
            context.update(target=body["target"], profile=body["profile"], variants=body.get("variants", {}))
        elif action == "suite":
            context.update(suite=body["suite"].strip(), candidate=body["candidate"].strip())
        with self.lock:
            if self.job["status"] == "running":
                raise RegistryError("a job is already running")
            self.job = {"status": "running", "action": action, "context": context, "events": []}

        def emit(event):
            with self.lock:
                self.job["events"].append(event)

        def run():
            try:
                if action == "prepare":
                    result = prepare(project, body["target"], profile=body["profile"], emit=emit,
                                     variants=body.get("variants"), registry=registry)
                elif action == "suite":
                    from verifier.worktree_suite import SuitePreflightError, verify_suite
                    try:
                        result = verify_suite(*suite_inputs, destination, registry=registry,
                                              emit=lambda case, side: emit({"case": case, "side": side}))
                    except SuitePreflightError as error:
                        result = error.report
                else:
                    result = stop(project, emit, registry=registry)
                with self.lock:
                    self.job.update(status="succeeded", result=result)
            except Exception as error:
                with self.lock:
                    self.job.update(status="failed", error=str(error) if isinstance(error, RegistryError)
                                    else "Local operation failed. Check project files and runtime availability.")

        threading.Thread(target=run, daemon=True).start()


def make_server(project, port=18770, *, registry=None, selection_file=None, restore_selection=True):
    control = Control(project, registry, selection_file, restore_selection)

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
                selection = control.selection
                registry = query.get("registry", [selection["registry"]])[0].strip() or None
                if url.path == "/api/info":
                    registries = (sorted(str(path / "registry.json") for path in REGISTRIES.iterdir()
                                         if (path / "registry.json").is_file()) if REGISTRIES.is_dir() else [])
                    return self.respond(200, {**selection,
                                              "registries": registries, "token": control.token,
                                              "injectorRoot": str(ASSETS.parent.parent)})
                if url.path == "/api/job":
                    return self.respond(200, control.snapshot())
                if url.path == "/api/project":
                    return self.respond(200, project_info(query.get("project", [selection["project"]])[0], registry=registry))
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
            comparison = self.path == "/api/observations/compare"
            if not editor and not comparison and self.path not in ("/api/project", "/api/project/pick", "/api/check", "/api/prepare", "/api/stop",
                                                                    "/api/suite/check", "/api/suite/run", "/api/suite/history"):
                return self.respond(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                limit = 6 * MAX_BYTES + 16384 if editor else 16384
                if comparison:
                    limit = 4 * MAX_OBSERVATION_BYTES + 1024
                if length <= 0 or length > limit:
                    raise ValueError()
                content = self.rfile.read(length)
                body = _parse_json(content.decode("utf-8")) if comparison else json.loads(content)
                if not isinstance(body, dict):
                    raise ValueError()
                if comparison:
                    from verifier.compare_observations import compare_observations
                    baseline = decode_document(body.get("baseline"), "observation")
                    candidate = decode_document(body.get("candidate"), "observation")
                    report = compare_observations(baseline, candidate)
                    for key in ("baseline", "candidate"):
                        if key in report:
                            report[key] = json.dumps(report[key], ensure_ascii=False, indent=2)
                    return self.respond(200, report)
                action = self.path.rsplit("/", 1)[1]
                if action == "pick":
                    return self.respond(200, control.pick_project(body))
                if action == "project":
                    return self.respond(200, control.load_project(body))
                if editor:
                    return self.respond(200, control.edit_registry(action, body))
                if self.path == "/api/suite/check":
                    from verifier.worktree_suite import check_suite
                    inputs = control.suite_inputs(body)
                    return self.respond(200, check_suite(*inputs, registry=control.registry_for(body)))
                if self.path == "/api/suite/history":
                    from verifier.suite_evidence import saved_run, saved_runs
                    project = body.get("project")
                    if not isinstance(project, str) or not project.strip() or "\x00" in project:
                        raise RegistryError("먼저 기준 프로젝트를 불러오세요.")
                    if "run" in body:
                        return self.respond(200, saved_run(VERIFICATION_RUNS, project, body["run"], body.get("case")))
                    return self.respond(200, {"runs": saved_runs(VERIFICATION_RUNS, project)})
                if action == "check":
                    keys = ("project", "target", "profile")
                    if not all(isinstance(body.get(key), str) and body[key].strip() for key in keys):
                        raise RegistryError("project, target and profile are required")
                    result = check_requirements(body["project"], body["target"], body["profile"],
                                                variants=body.get("variants"), registry=control.registry_for(body))
                    return self.respond(200, result)
                control.start("suite" if self.path == "/api/suite/run" else action, body)
                self.respond(202, {"status": "running"})
            except RegistryConflict as error:
                self.respond(409, {"error": str(error)})
            except RegistryError as error:
                self.respond(400, {"error": str(error)})
            except UnicodeError:
                self.respond(400, {"error": "registry file must be UTF-8"})
            except (ValueError, RecursionError):
                self.respond(400, {"error": "invalid request or registry text"})
            except OSError:
                self.respond(400, {"error": "cannot read or save the selected registry"})

    return LoopbackHTTPServer(("127.0.0.1", port), Handler)


def serve(project, port=18770, open_browser=False, *, registry=None, restore_selection=True):
    if open_browser and port:
        url = f"http://127.0.0.1:{port}"
        try:
            with build_opener(ProxyHandler({})).open(url + "/api/info", timeout=1) as response:
                info = json.load(response)
            if info.get("injectorRoot") == str(ASSETS.parent.parent):
                if registry is not None and (info.get("project"), info.get("registry")) != (
                        str(Path(project).resolve()), str(registry_path(project, registry))):
                    raise RegistryError("Injector is already running on this port; select the paths in the browser or use another --port")
                webbrowser.open(url)
                return
        except (OSError, ValueError):
            pass
    server = make_server(project, port, registry=registry, selection_file=WEB_SELECTION,
                         restore_selection=restore_selection)
    url = f"http://127.0.0.1:{server.server_port}"
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
