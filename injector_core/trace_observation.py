"""Collect a scenario's correlated HTTP and Kafka evidence from local Loki."""
from contextlib import nullcontext
from http.client import HTTPException
import json
import time
from urllib.parse import urlencode
from uuid import uuid4

from .observation import _endpoint_url, _exchange, _project_fields, _scenario_inputs
from .observation_contract import validate_document
from .registry import RegistryError, _parse_json
from .resolution import selected_variant


_MAX_EVENTS = 128
_EVENT_FIELDS = {
    "http_request": ("method", "path", "status"),
    "http_dependency": ("dependency", "method", "path", "status"),
    "kafka_publish": ("topic",),
    "kafka_consume": ("topic",),
}


def _selector(event):
    return event["service"], event["event"], event.get("dependency")


def _events(content, request_id, services):
    document = _parse_json(content.decode("utf-8"))
    if document["status"] != "success" or document["data"]["resultType"] != "streams":
        raise ValueError("expected Loki stream data")
    events = []
    seen = 0
    for stream in document["data"]["result"]:
        service = stream["stream"].get("service")
        for _, raw in stream["values"]:
            seen += 1
            if seen > _MAX_EVENTS:
                raise ValueError("too many correlated log lines")
            if service not in services:
                continue
            line = _parse_json(raw)
            if line.get("requestId") != request_id:
                continue
            details = line.get("details", {})
            kind = details.get("traceKind", line.get("event"))
            if kind in _EVENT_FIELDS:
                event = {"service": service, "event": kind, **{field: details.get(field) for field in _EVENT_FIELDS[kind]}}
                events.append(validate_document(event, "traceEvent"))
    return sorted(events, key=lambda event: json.dumps(event, sort_keys=True))


class TraceObservation:
    def __init__(self, scenario):
        self.scenario = scenario
        self.trace = scenario["trace"]
        self.digest, self.body = _scenario_inputs(scenario)

    def _route(self, data, plan):
        nodes = {node["id"]: node for node in data["nodes"]}
        profile = data["profiles"][plan["profile"]]
        target = plan["targets"][0]
        _, app = selected_variant(nodes, profile, target)
        if app["execution"]["type"] not in ("process", "compose"):
            raise RegistryError("trace observation requires an automatically started target")
        self.target = _endpoint_url(app, self.scenario["targetEndpoint"])
        if self.trace["node"] not in plan["order"]:
            raise RegistryError("trace collector must be in the target dependency plan")
        _, collector = selected_variant(nodes, profile, self.trace["node"])
        self.collector = _endpoint_url(collector, self.trace["endpoint"])
        steps = {step["node"]: step for step in plan["steps"] if step["kind"] == "application"}
        self.services = set(steps)
        for event in self.trace["requiredEvents"]:
            service, _, dependency = _selector(event)
            if service not in steps or dependency is not None and dependency not in steps[service]["dependencies"]:
                raise RegistryError("required trace event is outside the selected application graph")

    def proxy(self, data, plan):
        self._route(data, plan)
        return nullcontext()

    def _missing(self, events):
        captured = {_selector(event) for event in events}
        return [event for event in self.trace["requiredEvents"] if _selector(event) not in captured]

    def _collect(self, request_id, started):
        query = '{app="' + self.trace["app"] + '"} | json | requestId="' + request_id + '"'
        parameters = urlencode({"query": query, "start": started - 5_000_000_000, "limit": _MAX_EVENTS + 1})
        route = self.collector.path.rstrip("/") + "/loki/api/v1/query_range?" + parameters
        deadline = time.monotonic() + self.trace["timeoutSeconds"]
        events, stable_since, reason = [], None, "query-unavailable"
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                status, _, content = _exchange(self.collector, "GET", route, timeout=min(2, remaining))
            except (OSError, HTTPException, ValueError):
                status = None
            if status != 200:
                stable_since, reason = None, "query-unavailable"
            else:
                try:
                    current = _events(content, request_id, self.services)
                except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
                    stable_since, reason = None, "invalid-events"
                else:
                    now = time.monotonic()
                    if current != events or stable_since is None:
                        stable_since = now
                    events = current
                    if self._missing(events):
                        reason = "missing-events"
                    elif now - stable_since >= 0.75:
                        return events, None
                    else:
                        reason = "unstable-events"
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))
        return events, reason

    def capture(self, plan):
        request_id = uuid4().hex
        headers = [("X-Request-Id", request_id)]
        if self.body is not None:
            headers.append(("Content-Type", "application/json"))
        request = self.scenario["request"]
        started = time.time_ns()
        try:
            status, returned, content = _exchange(self.target, request["method"], request["path"], self.body, headers)
        except (OSError, HTTPException, ValueError) as error:
            raise RegistryError("could not complete the HTTP scenario against the trace target") from error
        echoed = [value for name, value in returned if name.lower() == "x-request-id"]
        events, reason = (self._collect(request_id, started) if echoed == [request_id]
                          else ([], "request-id-mismatch"))
        try:
            fields = _project_fields(content, self.scenario.get("targetFields", []))
        except (ValueError, RecursionError):
            fields, reason = {}, "invalid-target-fields"
        result = {"schemaVersion": 2, "scenario": self.scenario["name"], "scenarioDigest": self.digest,
                  "profile": plan["profile"], "targetNode": plan["targets"][0],
                  "variants": {step["node"]: step["variant"] for step in plan["steps"]},
                  "coverage": "incomplete" if reason else "observed", "target": {"status": status, "fields": fields},
                  "events": events, "missingEvents": self._missing(events)}
        if reason:
            result["reason"] = reason
        return validate_document(result, "observation")
