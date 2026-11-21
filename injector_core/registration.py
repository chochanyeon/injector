"""Review a discovery draft and assemble a single runtime profile without launching it."""
import json
from pathlib import Path
import re

from .planning import build_plan
from .registry import RegistryError, _parse_json, _project_path, parse_registry


def _items(data, field):
    values = data.get(field)
    if not isinstance(values, list) or not all(isinstance(value, dict) for value in values):
        raise RegistryError(f"{field}: expected a list of objects")
    return values


def _pointer(data, pointer):
    if not isinstance(pointer, str) or not pointer.startswith("/") or re.search(r"~(?![01])", pointer):
        raise RegistryError("evidence or finding must point to a draft field")
    try:
        for part in pointer[1:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(data, list):
                if not re.fullmatch(r"0|[1-9][0-9]*", part):
                    raise ValueError()
                data = data[int(part)]
            else:
                data = data[part]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise RegistryError("evidence or finding points to an unknown draft field") from error


def inspect_draft(data):
    if not isinstance(data, dict) or (data.get("draftVersion"), data.get("status")) != ("0.1", "draft"):
        raise RegistryError("expected registration draft version 0.1")
    nodes = {}
    for index, node in enumerate(_items(data, "nodes")):
        name = node.get("id")
        if not isinstance(name, str) or not name or name in nodes:
            raise RegistryError(f"nodes/{index}: expected a unique node ID")
        endpoints = node.get("endpoints")
        if endpoints is not None:
            endpoint_ids = [endpoint.get("id") for endpoint in _items(node, "endpoints")]
            if not all(isinstance(key, str) and key for key in endpoint_ids) or len(set(endpoint_ids)) != len(endpoint_ids):
                raise RegistryError(f"nodes/{index}: invalid or duplicate endpoint ID")
            endpoints = set(endpoint_ids)
        nodes[name] = endpoints
    for index, edge in enumerate(_items(data, "dependencies")):
        caller, provider = edge.get("from"), edge.get("to")
        if not all(isinstance(value, str) and value in nodes for value in (caller, provider)):
            raise RegistryError(f"dependencies/{index}: unknown caller or provider")
        endpoint = edge.get("endpoint")
        if endpoint is not None and (not isinstance(endpoint, str)
                or nodes[provider] is not None and endpoint not in nodes[provider]):
            raise RegistryError(f"dependencies/{index}: unknown provider endpoint")
        for rule in _items(edge, "injections"):
            source = rule.get("source")
            if not isinstance(source, dict) or source.get("node") != provider or source.get("endpoint") != edge.get("endpoint"):
                raise RegistryError(f"dependencies/{index}: injection must reference the recorded provider and endpoint")
    for item in _items(data, "evidence"):
        _pointer(data, item.get("field"))
        locations = _items(item, "locations")
        if item.get("status") not in ("observed", "inferred", "proposed") or not (locations or item.get("status") == "proposed"):
            raise RegistryError("evidence needs a status and source locations for observed or inferred claims")
        for location in locations:
            if (not isinstance(location.get("path"), str) or not location["path"]
                    or type(location.get("line")) is not int or location["line"] < 1):
                raise RegistryError("evidence source needs a path and positive line number")
    blockers = []
    for item in _items(data, "findings"):
        _pointer(data, item.get("field"))
        if item.get("severity") == "blocking":
            name = item.get("id")
            blockers.append(name if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]+", name) else "unnamed")
    _items(data, "nameMappings")
    return {"nodes": len(nodes), "dependencies": len(data["dependencies"]), "blockers": blockers}


def _required(item, field, path):
    if not isinstance(item, dict) or item.get(field) is None:
        raise RegistryError(f"{path}/{field}: unresolved")
    return item[field]


def convert_draft(data, project, destination):
    summary = inspect_draft(data)
    if summary["blockers"]:
        raise RegistryError("resolve draft blockers before conversion: " + ", ".join(summary["blockers"]))
    scope = data.get("scope")
    profile = _required(scope, "profile", "scope")
    targets = _required(scope, "targets", "scope")
    if not isinstance(profile, str) or not isinstance(targets, list):
        raise RegistryError("scope needs a profile name and a list of targets")
    evidence_fields = {item["field"] for item in data["evidence"]}
    for item in data["evidence"]:
        for location in item["locations"]:
            path = _project_path(project, location["path"], "evidence source")
            try:
                with path.open(encoding="utf-8", errors="replace") as source:
                    if any(index == location["line"] for index, _ in enumerate(source, 1)):
                        continue
            except OSError:
                pass
            raise RegistryError(f"{item['field']}: evidence source file or line does not exist")
    for section in ("nodes", "dependencies"):
        for index in range(len(data[section])):
            pointer = f"/{section}/{index}"
            if not any(field == pointer or field.startswith(pointer + "/") for field in evidence_fields):
                raise RegistryError(f"{pointer}: missing evidence")

    nodes = {}
    for index, node in enumerate(data["nodes"]):
        path = f"nodes/{index}"
        launch = _required(node, "execution", path)
        where = path + "/execution"
        mode = _required(launch, "mode", where)
        fields = {"intellij": ("projectPath", "module", "mainClass"),
                  "process": ("workingDirectory", "command"),
                  "compose": ("file", "service", "projectName"), "external": ()}
        if not isinstance(mode, str) or mode not in fields:
            raise RegistryError(f"{where}/mode: unsupported execution type")
        execution = {"type": mode, **{key: _required(launch, key, where) for key in fields[mode]}}
        endpoints = {}
        for endpoint in _items(node, "endpoints"):
            key = _required(endpoint, "id", path + "/endpoints")
            if not isinstance(key, str) or key in endpoints:
                raise RegistryError(f"{path}/endpoints: invalid or duplicate endpoint ID")
            addresses = {}
            for address in _items(endpoint, "addresses"):
                context = address.get("from")
                if context not in ("host", "container") or context in addresses:
                    raise RegistryError(f"{path}/endpoints: invalid or duplicate address context")
                addresses[context] = {key: value for key, value in address.items() if key != "from"}
            endpoints[key] = {**{key: _required(endpoint, key, path + "/endpoints") for key in ("protocol", "bind")},
                              "addresses": addresses}
        variant = {"execution": execution, "endpoints": endpoints, "dependencies": [], "injections": [],
                   "readiness": _required(node, "readiness", path)}
        for key, target in (("environment", "env"), ("vmOptions", "vmOptions"),
                            ("vmProperties", "vmProperties"), ("springProperties", "springProperties")):
            if key in launch:
                variant[target] = _required(launch, key, where)
        kind = node.get("kind")
        if kind not in ("application", "infrastructure", "mock", "external"):
            raise RegistryError(f"{path}/kind: unsupported node kind")
        nodes[node["id"]] = {"id": node["id"], "kind": "application" if kind == "application" else "infrastructure",
                             "variants": {"local": variant}}
    for edge in data["dependencies"]:
        caller = nodes[edge["from"]]["variants"]["local"]
        provider = nodes[edge["to"]]["variants"]["local"]
        name = edge.get("endpoint")
        if name is not None and (not isinstance(name, str) or name not in provider["endpoints"]):
            raise RegistryError(f'{edge["from"]}: unknown dependency endpoint on {edge["to"]}')
        if edge["to"] not in caller["dependencies"]:
            caller["dependencies"].append(edge["to"])
        for rule in edge["injections"]:
            source = rule["source"]
            caller["injections"].append({"channel": rule.get("channel"), "key": rule.get("key"),
                "source": {"node": source["node"], "endpoint": source.get("endpoint"),
                           "context": source.get("from"), "component": source.get("component")}})
    mappings = [{"hostname": item.get("hostname"), "address": item.get("address"),
                 "method": _required(item, "mechanism", "nameMappings")} for item in data["nameMappings"]]
    registry = {"schemaVersion": "1.1", "nodes": list(nodes.values()), "profiles": {
        profile: {"targets": targets, "selections": {key: "local" for key in nodes}}}}
    if mappings:
        registry["nameMappings"] = mappings
    verified = parse_registry(json.dumps(registry), project, destination)
    plan = build_plan(verified, profile)
    if data.get("startupOrder") != plan["order"]:
        raise RegistryError("startupOrder does not match the selected dependency plan")
    if set(plan["order"]) != nodes.keys():
        raise RegistryError("draft contains nodes outside the selected dependency graph")
    ports = {}
    for name in plan["order"]:
        variant = nodes[name]["variants"]["local"]
        if variant["execution"]["type"] == "external":
            continue
        for endpoint in variant["endpoints"].values():
            address = endpoint["addresses"].get("host")
            if address:
                key = (address["host"].rstrip(".").lower(), address["port"])
                if key in ports and ports[key] != name:
                    raise RegistryError(f"{name}: host port conflicts with {ports[key]}")
                ports[key] = name
    return registry, plan


def run_registration(command, draft, project, output=None):
    data = _parse_json(Path(draft).read_text(encoding="utf-8"))
    if command == "draft-check":
        return inspect_draft(data)
    root = Path(project).resolve()
    if not root.is_dir():
        raise RegistryError("source project folder does not exist")
    requested = Path(output)
    destination = requested.parent.resolve() / requested.name
    registry, plan = convert_draft(data, root, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = destination.open("x", encoding="utf-8", newline="\n")
    except FileExistsError as error:
        raise RegistryError("output already exists; choose a new candidate file to review") from error
    try:
        with handle:
            handle.write(json.dumps(registry, ensure_ascii=False, indent=2) + "\n")
    except OSError:
        destination.unlink(missing_ok=True)
        raise
    return {"profile": plan["profile"], "order": plan["order"], "output": str(destination)}
