"""Execute a validated dependency plan. Persist identities, never resolved values."""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import uuid

import psutil

from .hostnames import check_resolution
from .planning import build_plan
from .registry import RegistryError, _project_path, _validate_references, load_registry
from .rendering import _artifact_path, render_node
from .resolution import resolve_node, selected_variant

_processes = {}


def project_info(project):
    data = load_registry(project)
    return {"project": str(Path(project).resolve()), "profiles": {
        name: {"targets": profile["targets"], "applications": [
            node["id"] for node in data["nodes"]
            if node["kind"] == "application" and node["id"] in profile["selections"]]}
        for name, profile in data["profiles"].items()}}


def select_plan(project, target, profile=None, mode=None):
    if profile and mode:
        raise RegistryError("choose either profile or mode")
    data = load_registry(project, profile)
    if mode:
        aliases = {"dummy": ("dummy", "local-mock", "mock"), "real": ("real", "local-real")}
        candidates = [name for name in aliases.get(mode, ()) if name in data["profiles"]]
        if len(candidates) != 1:
            raise RegistryError("mode needs exactly one matching profile; use --profile explicitly")
        profile = candidates[0]
    if profile not in data["profiles"]:
        raise RegistryError("select an existing profile or mode")
    data = deepcopy(data)
    data["profiles"][profile]["targets"] = [target]
    _validate_references(data, Path(project).resolve(), profile)
    return data, build_plan(data, profile)


def _directory(project):
    root = Path(project).resolve()
    directory = root / ".local" / "injector"
    _artifact_path(root, directory / "session.json")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@contextmanager
def _lock(directory):
    """OS lock is released even when the CLI or web server crashes."""
    path = directory / "runtime.lock"
    _artifact_path(directory.parent.parent, path)
    with path.open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise RegistryError("another prepare or stop is running for this project") from error
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise RegistryError("another prepare or stop is running for this project") from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _docker(arguments, *, env=None, timeout=180):
    try:
        result = subprocess.run(["docker", *arguments], env=env, capture_output=True,
                                text=True, encoding="utf-8", timeout=timeout,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RegistryError("Docker command unavailable or timed out; check Docker Desktop") from error
    if result.returncode:
        raise RegistryError("Docker command failed; check Docker Desktop, image/build and service configuration")
    return result.stdout.strip()


def _containers(*filters):
    arguments = ["ps", "-aq"]
    for value in filters:
        arguments.extend(["--filter", "label=" + value])
    return _docker(arguments).split()


def _save(directory, session):
    temporary = directory / "session.tmp"
    _artifact_path(directory.parent.parent, temporary)
    temporary.write_text(json.dumps(session, indent=2), encoding="utf-8")
    temporary.replace(directory / "session.json")


def _stop(directory, emit):
    path = directory / "session.json"
    if not path.exists():
        return
    session = json.loads(path.read_text(encoding="utf-8"))
    for resource in reversed(session["resources"]):
        emit({"node": resource["node"], "phase": "stopping"})
        if resource["type"] == "compose":
            ids = _containers("io.injector.session=" + session["id"], "io.injector.node=" + resource["node"])
            if ids:
                _docker(["rm", "-f", *ids])
        else:
            try:
                process = psutil.Process(resource["pid"])
                if process.create_time() != resource["created"]:
                    raise RegistryError("process identity changed; refusing to stop an unrelated process")
                processes = [*process.children(recursive=True), process]
                for child in processes:
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
                _, alive = psutil.wait_procs(processes, timeout=3)
                for child in alive:
                    child.kill()
                psutil.wait_procs(alive, timeout=3)
            except psutil.NoSuchProcess:
                pass
            handle = _processes.pop(resource["pid"], None)
            if handle is not None:
                handle.wait(timeout=3)
    path.unlink()


def stop(project, emit=lambda event: None):
    directory = _directory(project)
    with _lock(directory):
        _stop(directory, emit)
    return {"status": "stopped", "project": str(Path(project).resolve())}


def _endpoint(variant):
    ready = variant["readiness"]
    if ready["type"] == "compose":
        return None
    endpoint = variant["endpoints"][ready["endpoint"]]
    address = endpoint["addresses"].get("host")
    if not address or address["host"] in ("0.0.0.0", "::", "*"):
        raise RegistryError("readiness needs a concrete host address")
    return address


def _wait(variant, alive, healthy):
    ready = variant["readiness"]
    address = _endpoint(variant)
    deadline = time.monotonic() + ready["timeoutSeconds"]
    opener = build_opener(ProxyHandler({}))
    while time.monotonic() < deadline:
        if not alive():
            raise RegistryError("process or container exited before readiness")
        try:
            if ready["type"] == "compose":
                if healthy():
                    return
            elif ready["type"] == "tcp":
                with socket.create_connection((address["host"], address["port"]), timeout=0.4):
                    return
            else:
                host = address["host"]
                if ":" in host:
                    host = "[" + host + "]"
                url = f"{address.get('scheme', 'http')}://{host}:{address['port']}{ready['path']}"
                with opener.open(url, timeout=0.4) as response:
                    if 200 <= response.status < 300:
                        return
        except (OSError, URLError, ValueError):
            pass
        time.sleep(0.1)
    raise RegistryError("readiness timed out")


def prepare(project, target, profile=None, mode=None, emit=lambda event: None):
    root = Path(project).resolve()
    data, plan = select_plan(root, target, profile, mode)
    profile = plan["profile"]
    nodes = {node["id"]: node for node in data["nodes"]}
    directory = _directory(root)
    with _lock(directory):
        selected = [(step["node"], selected_variant(nodes, data["profiles"][profile], step["node"])[1])
                    for step in plan["steps"]]
        check_resolution(data, (variant for _, variant in selected), root)
        prepared = []
        compose_keys = set()
        # Resolve every node and validate runners before starting any resources.
        for node, variant in selected:
            execution = variant["execution"]
            kind = execution["type"]
            settings = resolve_node(data, profile, node, defer_spring_env=kind == "intellij")
            _endpoint(variant)
            if kind == "intellij":
                if node != target:
                    raise RegistryError("an IntelliJ dependency needs a process or compose variant")
                artifact = render_node(data, root, profile, node, allow_plain=True)
            else:
                if settings.spring_properties:
                    raise RegistryError("runtime Spring YAML currently requires an IntelliJ target")
                if kind == "process":
                    working = _project_path(root, execution["workingDirectory"], "process workingDirectory")
                    if not working.is_dir() or not shutil.which(execution["command"][0]):
                        raise RegistryError("process command or working directory is unavailable")
                    if settings.jvm_arguments() and Path(execution["command"][0]).stem.lower() != "java":
                        raise RegistryError("VM settings on a process require a java executable")
                elif kind == "compose":
                    if settings.jvm_arguments():
                        raise RegistryError("Compose VM settings need an explicit JVM command in the Compose service")
                    key = (execution["projectName"], execution["service"])
                    if key in compose_keys:
                        raise RegistryError("multiple nodes select the same Compose service")
                    compose_keys.add(key)
                    compose_file = _project_path(root, execution["file"], "Compose file")
                    command = ["compose", "-p", execution["projectName"], "-f", str(compose_file)]
                    config = json.loads(_docker([*command, "config", "--format", "json"]))
                    service = config["services"].get(execution["service"])
                    if not service:
                        raise RegistryError("selected Compose service does not exist")
                    health = service.get("healthcheck", {})
                    if variant["readiness"]["type"] == "compose" and (
                            not health or health.get("disable") or health.get("test") == ["NONE"]):
                        raise RegistryError("compose readiness requires a healthcheck")
                elif kind != "external":
                    raise RegistryError("unsupported runner")
            prepared.append((node, variant, settings))

        emit({"phase": "planned", "order": plan["order"]})
        _stop(directory, emit)
        session = {"id": uuid.uuid4().hex, "profile": profile, "target": target, "resources": []}
        _save(directory, session)
        try:
            for node, variant, settings in prepared:
                execution = variant["execution"]
                kind = execution["type"]
                emit({"node": node, "phase": "starting"})
                if kind == "intellij":
                    emit({"node": node, "phase": "debug-ready"})
                    continue
                if kind != "external":
                    for endpoint in variant["endpoints"].values():
                        address = endpoint["addresses"].get("host")
                        if address:
                            try:
                                with socket.create_connection((address["host"], address["port"]), timeout=0.2):
                                    raise RegistryError("registered host port is already in use")
                            except (ConnectionError, TimeoutError, socket.gaierror):
                                pass
                environment = {**os.environ, **settings.env}
                if kind == "process":
                    command = execution["command"]
                    process = subprocess.Popen([command[0], *settings.jvm_arguments(), *command[1:]],
                        cwd=_project_path(root, execution["workingDirectory"], "process workingDirectory"), env=environment,
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        start_new_session=os.name == "posix",
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                    _processes[process.pid] = process
                    session["resources"].append({"node": node, "type": kind, "pid": process.pid,
                                                  "created": psutil.Process(process.pid).create_time()})
                    _save(directory, session)
                    alive = lambda: process.poll() is None
                    healthy = lambda: False
                elif kind == "compose":
                    name, service = execution["projectName"], execution["service"]
                    if _containers("com.docker.compose.project=" + name, "com.docker.compose.service=" + service):
                        raise RegistryError("Compose service already exists outside this session; choose a dedicated projectName")
                    # Write only interpolation references; actual values stay in the child environment.
                    variables = {key: f"INJECTOR_VALUE_{index}" for index, key in enumerate(settings.env)}
                    environment.update({variables[key]: value for key, value in settings.env.items()})
                    override = directory / f"compose-{node}.json"
                    _artifact_path(root, override)
                    override.write_text(json.dumps({"services": {service: {
                        "environment": {key: "${" + reference + "?}" for key, reference in variables.items()},
                        "labels": {"io.injector.session": session["id"], "io.injector.node": node}}}}), encoding="utf-8")
                    session["resources"].append({"node": node, "type": kind})
                    _save(directory, session)
                    compose_file = _project_path(root, execution["file"], "Compose file")
                    _docker(["compose", "-p", name, "-f", str(compose_file), "-f", str(override),
                             "up", "-d", "--build", "--no-deps", service], env=environment)
                    ids = _containers("io.injector.session=" + session["id"], "io.injector.node=" + node)
                    if len(ids) != 1:
                        raise RegistryError("expected one container for the selected Compose service")
                    def state():
                        return json.loads(_docker(["inspect", "--format", "{{json .State}}", ids[0]]))
                    alive = lambda: state()["Running"]
                    healthy = lambda: state().get("Health", {}).get("Status") == "healthy"
                else:
                    alive, healthy = lambda: True, lambda: False
                emit({"node": node, "phase": "waiting"})
                _wait(variant, alive, healthy)
                emit({"node": node, "phase": "ready"})
            result = {"status": "ready", "project": str(root), "profile": profile,
                      "target": target, "order": plan["order"]}
            if prepared[-1][1]["execution"]["type"] == "intellij":
                result["runConfiguration"] = str(artifact.run_path)
                result["next"] = f"IntelliJ: select Injector-{profile}-{target} and press Debug"
            return result
        except BaseException:
            emit({"phase": "rollback"})
            _stop(directory, emit)
            raise
