"""Execute a validated dependency plan. Persist identities, never resolved values."""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import uuid

import psutil

from .hostnames import check_resolution
from .planning import build_plan
from .process_runner import terminate_job
from .registry import RegistryError, _project_path, _validate_references, load_registry
from .rendering import _artifact_path, plan_render
from .resolution import resolve_node, selected_variant

_processes = {}


def parse_variants(entries):
    variants = {}
    for entry in entries:
        node, _, variant = entry.partition("=")
        if not node or not variant or node in variants:
            raise RegistryError("use one node=variant entry per node")
        variants[node] = variant
    return variants


def _applications(data, profile):
    return [node["id"] for node in data["nodes"]
            if node["kind"] == "application" and node["id"] in profile["selections"]]


def project_info(project):
    data = load_registry(project)
    variants = {node["id"]: list(node["variants"]) for node in data["nodes"] if len(node["variants"]) > 1}
    return {"project": str(Path(project).resolve()), "profiles": {
        name: {"targets": profile["targets"], "applications": _applications(data, profile),
               "variantChoices": {node: {"default": selected, "options": variants[node]}
                                  for node, selected in profile["selections"].items() if node in variants}}
        for name, profile in data["profiles"].items()}}


def select_plan(project, target, profile=None, mode=None, *, variants=None):
    """Plan one app, or all apps selected by the profile when target is None."""
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
    selection = data["profiles"][profile]
    if variants is not None:
        if not isinstance(variants, dict) or not all(isinstance(value, str) for value in variants.values()):
            raise RegistryError("variants must map node IDs to variant names")
        for node, variant in variants.items():
            if node not in selection["selections"]:
                raise RegistryError(f"node {node} has no selection in profile {profile}")
            selection["selections"][node] = variant
    selection["targets"] = [target] if target is not None else _applications(data, selection)
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


def _session(directory):
    path = directory / "session.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _owned_process(resource):
    try:
        process = psutil.Process(resource["pid"])
        if process.create_time() != resource["created"]:
            raise RegistryError("process identity changed; refusing to stop an unrelated process")
        return process
    except psutil.NoSuchProcess:
        return None


def _stop_process(resource):
    pid = resource["pid"]
    runner = resource.get("runner")
    process = _owned_process(resource)
    try:
        if runner and os.name == "nt":
            # If the runner has not joined its job yet, it cannot launch anything.
            if not terminate_job(runner) and process is not None:
                process.terminate()
                process.wait(timeout=3)
                terminate_job(runner)
        elif runner and process is not None:
            try:
                processes = [*process.children(recursive=True), process]
                os.killpg(pid, signal.SIGTERM)
                _, alive = psutil.wait_procs(processes, timeout=3)
                if alive:
                    os.killpg(pid, signal.SIGKILL)
                    psutil.wait_procs(alive, timeout=3)
            except ProcessLookupError:
                pass
        elif process is not None:
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
    handle = _processes.get(pid)
    if handle is not None:
        handle.wait(timeout=3)
        _processes.pop(pid)


def _stop(directory, emit):
    session = _session(directory)
    if session is None:
        return
    for resource in reversed(session["resources"]):
        emit({"node": resource["node"], "phase": "stopping"})
        if resource["type"] == "compose":
            ids = _containers("io.injector.session=" + session["id"], "io.injector.node=" + resource["node"])
            if ids:
                _docker(["rm", "-f", *ids])
        else:
            _stop_process(resource)
    (directory / "session.json").unlink()


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


def _occupied(address):
    try:
        with socket.create_connection((address["host"], address["port"]), timeout=0.2) as connection:
            return connection.getpeername()[:2]
    except (ConnectionError, TimeoutError, socket.gaierror):
        return None


def _owned_listeners(session):
    listeners = set()
    if session is None:
        return listeners
    for resource in session["resources"]:
        if resource["type"] == "compose":
            ids = _containers("io.injector.session=" + session["id"], "io.injector.node=" + resource["node"])
            for container in ids:
                ports = json.loads(_docker(["inspect", "--format", "{{json .NetworkSettings.Ports}}", container]))
                for protocol, bindings in (ports or {}).items():
                    if protocol.endswith("/tcp"):
                        listeners.update((entry["HostIp"], int(entry["HostPort"])) for entry in bindings or [])
        else:
            process = _owned_process(resource)
            if process is None:
                continue
            try:
                members = [process, *process.children(recursive=True)]
            except psutil.NoSuchProcess:
                continue
            for member in members:
                try:
                    listeners.update((conn.laddr.ip, conn.laddr.port) for conn in member.net_connections("tcp")
                                     if conn.status == psutil.CONN_LISTEN)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
    return listeners


def _process_command(execution, working, environment):
    command, *arguments = execution["command"]
    if not working.is_dir():
        raise RegistryError("process command or working directory is unavailable")
    if os.path.dirname(command):
        candidates = [working / command]
    else:
        search_path = environment.get("PATH", os.defpath).split(os.pathsep)
        if os.name == "nt" and "NODEFAULTCURRENTDIRECTORYINEXEPATH" not in environment:
            search_path.insert(0, "")
        candidates = [working / directory / command for directory in search_path]
    extensions = [""]
    if os.name == "nt":
        # Python 3.10's shutil.which does not try PATHEXT on explicit paths.
        suffixes = environment.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(os.pathsep)
        if Path(command).suffix.lower() not in {suffix.lower() for suffix in suffixes}:
            extensions.extend(suffixes)
    for candidate in candidates:
        for extension in extensions:
            executable = Path(str(candidate) + extension)
            if executable.is_file() and os.access(executable, os.X_OK):
                return [str(executable), *arguments]
    raise RegistryError("process command or working directory is unavailable")


def _start_process(directory, session, node, command, working, environment):
    runner = f"Injector-{session['id']}-{node}"
    try:
        process = subprocess.Popen([sys.executable, "-I", str(Path(__file__).with_name("process_runner.py")), runner, *command],
            cwd=working, env=environment, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=os.name == "posix",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except OSError as error:
        raise RegistryError("could not start managed process runner") from error
    try:
        created = psutil.Process(process.pid).create_time()
        session["resources"].append({"node": node, "type": "process", "pid": process.pid,
                                     "created": created, "runner": runner})
        _processes[process.pid] = process
        _save(directory, session)
        process.stdin.write(b"1")
        process.stdin.flush()
    except (OSError, psutil.NoSuchProcess) as error:
        raise RegistryError("could not start managed process") from error
    finally:
        try:
            process.stdin.close()
        except BrokenPipeError:
            pass
    return process


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


def prepare(project, target, profile=None, mode=None, emit=lambda event: None, *, variants=None):
    if target is None:
        raise RegistryError("prepare requires an application target")
    root = Path(project).resolve()
    data, plan = select_plan(root, target, profile, mode, variants=variants)
    profile = plan["profile"]
    nodes = {node["id"]: node for node in data["nodes"]}
    directory = _directory(root)
    with _lock(directory):
        selected = [(step["node"], selected_variant(nodes, data["profiles"][profile], step["node"])[1])
                    for step in plan["steps"]]
        check_resolution(data, (variant for _, variant in selected), root)
        prepared = []
        compose_keys = set()
        addresses = []
        # Resolve every node and validate runners before starting any resources.
        for node, variant in selected:
            execution = variant["execution"]
            kind = execution["type"]
            settings = resolve_node(data, profile, node, defer_spring_env=kind == "intellij")
            _endpoint(variant)
            command = working = None
            if kind == "intellij":
                if node != target:
                    raise RegistryError("an IntelliJ dependency needs a process or compose variant")
                artifact, write_config = plan_render(data, root, profile, node, allow_plain=True)
            else:
                if kind != "external":
                    addresses.extend(endpoint["addresses"]["host"] for endpoint in variant["endpoints"].values()
                                     if "host" in endpoint["addresses"])
                if settings.spring_properties:
                    raise RegistryError("runtime Spring YAML currently requires an IntelliJ target")
                if kind == "process":
                    working = _project_path(root, execution["workingDirectory"], "process workingDirectory")
                    command = _process_command(execution, working, {**os.environ, **settings.env})
                    if settings.jvm_arguments() and Path(command[0]).stem.lower() != "java":
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
            prepared.append((node, variant, settings, command, working))

        occupied = {peer for address in addresses if (peer := _occupied(address)) is not None}
        if occupied:
            listeners = _owned_listeners(_session(directory))
            for host, port in occupied:
                wildcard = "::" if ":" in host else "0.0.0.0"
                if (host, port) not in listeners and (wildcard, port) not in listeners:
                    raise RegistryError("registered host port is already in use")
        emit({"phase": "planned", "order": plan["order"]})
        _stop(directory, emit)
        session = {"id": uuid.uuid4().hex, "profile": profile, "target": target, "resources": []}
        _save(directory, session)
        try:
            for node, variant, settings, command, working in prepared:
                execution = variant["execution"]
                kind = execution["type"]
                emit({"node": node, "phase": "starting"})
                if kind == "intellij":
                    write_config()
                    emit({"node": node, "phase": "debug-ready"})
                    continue
                if kind != "external":
                    for endpoint in variant["endpoints"].values():
                        address = endpoint["addresses"].get("host")
                        if address and _occupied(address):
                            raise RegistryError("registered host port is already in use")
                environment = {**os.environ, **settings.env}
                if kind == "process":
                    process = _start_process(directory, session, node,
                        [command[0], *settings.jvm_arguments(), *command[1:]], working, environment)
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
