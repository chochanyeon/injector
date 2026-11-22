"""Record local dependency behavior while Injector owns the session."""
from contextlib import contextmanager
from hashlib import sha256
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler
from ipaddress import ip_address
import json
import math
from pathlib import Path
import threading
from urllib.parse import parse_qsl, urlsplit

from .loopback import LoopbackHTTPServer
from .observation_contract import MAX_OBSERVATION_BYTES, read_document, validate_document
from .registry import RegistryError, _parse_json
from .resolution import _address_value, selected_variant
from .runtime import check_observation_idle, prepare, select_plan


_MAX_BODY = 1024 * 1024
_HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
                "te", "trailer", "transfer-encoding", "upgrade", "proxy-connection"}


def _endpoint_url(variant, name):
    endpoint = variant["endpoints"].get(name)
    if not endpoint or endpoint["protocol"] != "http" or "host" not in endpoint["addresses"]:
        raise RegistryError("observation needs a host HTTP endpoint")
    url = _address_value(endpoint, {"context": "host", "component": "url"})
    parsed = urlsplit(url)
    try:
        local = ip_address(parsed.hostname).is_loopback
    except ValueError:
        local = False
    if not local:
        raise RegistryError("observation needs a literal loopback address")
    return parsed


def _filtered(headers, *excluded):
    items = list(headers)
    connection_fields = {key.strip().lower() for name, value in items if name.lower() == "connection"
                         for key in value.split(",")}
    skip = _HOP_HEADERS | connection_fields | set(excluded)
    return [(name, value) for name, value in items if name.lower() not in skip]


def _exchange(endpoint, method, path, body=None, headers=(), *, timeout=8):
    connection = HTTPConnection(endpoint.hostname, endpoint.port, timeout=timeout)
    try:
        connection.putrequest(method, path, skip_accept_encoding=True)
        for name, value in headers:
            connection.putheader(name, value)
        if body is not None:
            connection.putheader("Content-Length", str(len(body)))
        connection.endheaders(body)
        with connection.getresponse() as response:
            content = response.read(_MAX_BODY + 1)
            if len(content) > _MAX_BODY or response.status < 200:
                raise ValueError("unsupported HTTP response")
            return response.status, response.getheaders(), content
    finally:
        connection.close()


def _project_query(query, keys):
    fields = {}
    if keys:
        for key, value in parse_qsl(query, keep_blank_values=True, errors="strict", max_num_fields=256):
            if key in keys:
                values = fields.setdefault(key, [])
                if len(values) == 16 or len(value) > 2048:
                    raise ValueError("capture query values must be bounded")
                values.append(value)
    return fields


def _project_fields(body, pointers):
    if not pointers:
        return {}
    data = _parse_json(body.decode("utf-8"))
    fields = {}
    for pointer in pointers:
        value = data
        try:
            for token in pointer[1:].split("/"):
                token = token.replace("~1", "/").replace("~0", "~")
                if isinstance(value, list):
                    if not token.isascii() or not token.isdecimal() or str(int(token)) != token:
                        raise KeyError(token)
                    value = value[int(token)]
                else:
                    value = value[token]
        except (KeyError, TypeError, IndexError):
            continue
        if (isinstance(value, (dict, list)) or isinstance(value, str) and len(value) > 2048
                or isinstance(value, float) and not math.isfinite(value)):
            raise ValueError("capture fields must be bounded JSON scalars")
        fields[pointer] = value
    return fields


def _scenario_inputs(scenario):
    digest = sha256(json.dumps(scenario, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()
    request = scenario["request"]
    body = json.dumps(request["json"], ensure_ascii=False, allow_nan=False).encode("utf-8") if "json" in request else None
    if body is not None and len(body) > _MAX_BODY:
        raise RegistryError("HTTP scenario input exceeds 1 MiB")
    return digest, body


class HTTPObservation:
    def __init__(self, scenario):
        self.scenario = scenario
        self.digest, self.body = _scenario_inputs(scenario)
        self.lock = threading.Lock()
        self.calls = []
        self.active = False
        self.failed = False
        self.pending = 0

    def _record(self, method, path, body, status, content):
        with self.lock:
            if not self.active:
                return
            if len(self.calls) == 16:
                self.failed = True
                return
            try:
                request = _project_fields(body, self.scenario.get("requestFields", []))
                response = _project_fields(content, self.scenario.get("responseFields", []))
                keys = self.scenario.get("requestQuery")
                query = _project_query(path.query, keys)
            except (ValueError, RecursionError):
                self.failed = True
                return
            call = {"method": method, "path": path.path, "status": status,
                    "requestFields": request, "responseFields": response}
            if keys is not None:
                call["requestQuery"] = query
            elif path.query:
                self.failed = True
            self.calls.append(call)

    def _route(self, data, plan):
        caller = plan["targets"][0]
        dependency, endpoint = self.scenario["dependency"], self.scenario["dependencyEndpoint"]
        nodes = {node["id"]: node for node in data["nodes"]}
        profile = data["profiles"][plan["profile"]]
        _, application = selected_variant(nodes, profile, caller)
        if application["execution"]["type"] != "process":
            raise RegistryError("HTTP observation currently requires a process target")
        if not any(rule["source"] == {"node": dependency, "endpoint": endpoint, "context": "host", "component": "url"}
                   for rule in application.get("injections", [])):
            raise RegistryError("the observed dependency needs a host URL injection on the target")
        _, provider = selected_variant(nodes, profile, dependency)
        self.target = _endpoint_url(application, self.scenario["targetEndpoint"])
        self.edge = {"caller": caller, "dependency": dependency, "endpoint": endpoint}
        return _endpoint_url(provider, endpoint)

    @contextmanager
    def proxy(self, data, plan):
        upstream = self._route(data, plan)
        caller, dependency, endpoint = (self.edge[key] for key in ("caller", "dependency", "endpoint"))
        observation = self

        class Proxy(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def relay(self):
                self.connection.settimeout(8)
                with observation.lock:
                    recording = observation.active
                    if recording:
                        observation.pending += 1
                try:
                    path = urlsplit(self.path)
                    lengths = self.headers.get_all("Content-Length", [])
                    size = int(lengths[0]) if lengths else 0
                    if (path.scheme or path.netloc or not path.path.startswith("/") or path.fragment
                            or len(path.path) > 2048 or len(lengths) > 1 or not 0 <= size <= _MAX_BODY
                            or self.headers.get("Transfer-Encoding")):
                        raise ValueError("unsupported HTTP request")
                    body = self.rfile.read(size)
                    if len(body) != size:
                        raise ValueError("incomplete HTTP body")
                    headers = _filtered(self.headers.items(), "host", "content-length")
                    status, headers, content = _exchange(upstream, self.command, self.path,
                                                         body if lengths else None, headers)
                    if recording:
                        observation._record(self.command, path, body, status, content)
                except (OSError, HTTPException, ValueError):
                    self.send_error(502, "HTTP observation proxy failed")
                    return
                finally:
                    if recording:
                        with observation.lock:
                            observation.pending -= 1
                self.send_response_only(status)
                for name, value in _filtered(headers, "content-length"):
                    self.send_header(name, value)
                if status not in (204, 304):
                    self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = relay

            def send_error(self, *args, **kwargs):
                with observation.lock:
                    if observation.active:
                        observation.failed = True
                super().send_error(*args, **kwargs)

        with LoopbackHTTPServer(("127.0.0.1", 0), Proxy) as server:
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            thread.start()
            try:
                yield {(caller, dependency, endpoint): f"http://127.0.0.1:{server.server_port}{upstream.path}"}
            finally:
                server.shutdown()
                thread.join()

    def capture(self, plan):
        request = self.scenario["request"]
        headers = (("Content-Type", "application/json"),) if self.body is not None else ()
        with self.lock:
            self.active = True
        try:
            status, _, content = _exchange(self.target, request["method"], request["path"], self.body, headers)
        except (OSError, HTTPException, ValueError) as error:
            raise RegistryError("could not complete the HTTP scenario against the target") from error
        finally:
            with self.lock:
                self.active = False
                if self.pending:
                    self.failed = True
        try:
            fields = _project_fields(content, self.scenario.get("targetFields", []))
        except (ValueError, RecursionError):
            fields = {}
            self.failed = True
        coverage = "incomplete" if self.failed else "observed" if self.calls else "unobserved"
        return validate_document({"schemaVersion": 1, "scenario": self.scenario["name"], "scenarioDigest": self.digest,
            "profile": plan["profile"], "edge": self.edge, "coverage": coverage, "calls": self.calls,
            "variants": {step["node"]: step["variant"] for step in plan["steps"]},
            "target": {"status": status, "fields": fields}}, "observation")


def _write_artifact(destination, result, *, limit=None):
    payload = (json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
    if limit is not None and len(payload) > limit:
        raise RegistryError("HTTP observation exceeds the 2 MiB file limit")
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = destination.open("xb")
    try:
        with handle:
            handle.write(payload)
    except OSError:
        destination.unlink(missing_ok=True)
        raise


def _record_http(project, target, profile, observation, destination, registry, emit=lambda event: None):
    if destination.exists() or destination.is_symlink():
        raise RegistryError("observation output already exists")
    result = prepare(project, target, profile, emit=emit, registry=registry, observation=observation)
    _write_artifact(destination, result, limit=MAX_OBSERVATION_BYTES)
    captured = "events" if "events" in result else "calls"
    return {"output": str(destination), "coverage": result["coverage"], captured: len(result[captured])}


def _observation_for(scenario):
    if scenario["schemaVersion"] == 2:
        from .trace_observation import TraceObservation
        return TraceObservation(scenario)
    return HTTPObservation(scenario)


def observe_http(project, target, profile, scenario_path, output, *, registry=None):
    scenario = read_document(Path(scenario_path), "scenario")
    return _record_http(project, target, profile, _observation_for(scenario), Path(output), registry)


def _comparison_projects(project, candidate):
    baseline, candidate = Path(project).resolve(), Path(candidate).resolve()
    if not baseline.is_dir() or not candidate.is_dir():
        raise RegistryError("baseline and candidate must be existing project directories")
    if baseline.samefile(candidate):
        raise RegistryError("baseline and candidate must be different project directories")
    return {"baseline": baseline, "candidate": candidate}


def _validate_fix_check(scenario, prove_fix):
    if prove_fix is not None:
        checks = {check["id"] for check in scenario.get("stateChecks", []) if check["when"] == "after"}
        checks.update(check["id"] for check in scenario.get("trace", {}).get("eventCounts", []))
        if "expect" in scenario:
            checks.add("response")
        if prove_fix not in checks:
            raise RegistryError("the fix check must name 'response', an after check or an event count check")


def _plan_observation(scenario, data, plan):
    observation = _observation_for(scenario)
    observation._route(data, plan)
    return observation


def _plan_comparison(checkouts, target, profile, scenario, registry, prove_fix):
    _validate_fix_check(scenario, prove_fix)
    observations = {}
    for side, checkout in checkouts.items():
        try:
            data, plan = select_plan(checkout, target, profile, registry=registry)
            observations[side] = _plan_observation(scenario, data, plan)
            check_observation_idle(checkout, registry=registry)
        except RegistryError as error:
            raise RegistryError(f"{side}: {error}") from error
    return observations


def _run_comparison(checkouts, target, profile, observations, destination, *, registry, prove_fix, emit):
    from verifier.compare_observations import compare_files

    try:
        destination.mkdir(parents=True)
    except FileExistsError as error:
        raise RegistryError("comparison output directory already exists") from error
    runs = {side: {"project": str(checkout), "status": "not-run", "events": []}
            for side, checkout in checkouts.items()}
    artifacts = {}
    interruption = None
    for side, checkout in checkouts.items():
        run = runs[side]
        artifact = destination / f"{side}.json"
        try:
            emit(side)
            _record_http(checkout, target, profile, observations[side], artifact, registry, run["events"].append)
        except RegistryError as error:
            run.update(status="failed", reason=str(error))
            report = {"verdict": "INCONCLUSIVE", "reason": f"{side} run did not complete"}
            break
        except KeyboardInterrupt as error:
            interruption = error
            run.update(status="interrupted", reason="execution interrupted")
            report = {"verdict": "INCONCLUSIVE", "reason": f"{side} run was interrupted"}
            break
        run["status"] = "recorded"
        artifacts[side] = str(artifact)
    else:
        report = compare_files(artifacts["baseline"], artifacts["candidate"], prove_fix=prove_fix)
    report_path = destination / "report.json"
    baseline_observation = observations["baseline"]
    report.update(scenario=baseline_observation.scenario["name"], scenarioDigest=baseline_observation.digest,
                  profile=profile, targetApp=target, runs=runs, artifacts=artifacts, report=str(report_path))
    if prove_fix is not None:
        report["fixCheck"] = prove_fix
    _write_artifact(report_path, report)
    if interruption is not None:
        raise interruption
    return report


def compare_worktrees(project, candidate, target, profile, scenario_path, output, *, registry=None,
                      emit=lambda side: None, prove_fix=None):
    checkouts = _comparison_projects(project, candidate)
    destination = Path(output)
    if destination.exists() or destination.is_symlink():
        raise RegistryError("comparison output directory already exists")
    scenario = read_document(Path(scenario_path), "scenario")
    observations = _plan_comparison(checkouts, target, profile, scenario, registry, prove_fix)
    return _run_comparison(checkouts, target, profile, observations, destination, registry=registry,
                           prove_fix=prove_fix, emit=emit)
