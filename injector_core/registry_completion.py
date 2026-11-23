"""Registry editor suggestions and draft-only JSON updates."""
import json
import os
from pathlib import Path
import re

from jsonschema import Draft202012Validator

from .registry import RegistryError, SCHEMA_PATHS, _check_schema, _parse_json, node_file_path, registry_path
from .registry_editor import MAX_BYTES, _document, _read, _require_regular_file
from .resolution import _address_value


_SCAN_LIMIT = 10000
_SKIP_DIRS = {"node_modules", "build", "target"}
_JSON_SPACE = re.compile(r"[ \t\r\n]*")


def _format_value(text, offset, value):
    line_start = text.rfind("\n", 0, offset) + 1
    prefix = text[line_start:offset]
    if line_start and not prefix.strip():
        return json.dumps(value, ensure_ascii=False, indent=2).replace("\n", "\n" + prefix)
    return json.dumps(value, ensure_ascii=False)


def _set_field(text, path, value):
    """Replace or add one property without reserializing unrelated values."""
    decoder = json.JSONDecoder()
    start = _JSON_SPACE.match(text).end()
    for key in path:
        cursor = _JSON_SPACE.match(text, start + 1).end()
        first = cursor
        while text[cursor] != "}":
            name, end = decoder.raw_decode(text, cursor)
            begin = _JSON_SPACE.match(text, _JSON_SPACE.match(text, end).end() + 1).end()
            _, end = decoder.raw_decode(text, begin)
            if name == key:
                start = begin
                break
            cursor = _JSON_SPACE.match(text, end).end()
            if text[cursor] == ",":
                cursor = _JSON_SPACE.match(text, cursor + 1).end()
        else:
            label = json.dumps(key, ensure_ascii=False)
            encoded = _format_value(text, first, value)
            if first == cursor:
                return text[:first] + f'{label}: {encoded}' + text[first:]
            padding = text[end:cursor]
            if "\n" in padding:
                padding = text[start + 1:first]
            else:
                padding = " "
            return text[:end] + f',{padding}{label}: {encoded}' + text[end:]
    return text[:start] + _format_value(text, cursor, value) + text[end:]


def _node_at(registry, filename, validator):
    try:
        path = node_file_path(registry, filename)
        _require_regular_file(path)
        node = _parse_json(_read(path).decode("utf-8"))
        _check_schema(validator.descend(node, validator.schema["$defs"]["node"]))
        return node
    except (OSError, ValueError):
        return None


def _paths(registry, validator, registered, ids):
    seen = 0
    candidates = []
    for directory, folders, files in os.walk(registry.parent):
        parent = Path(directory)
        folders[:] = sorted(folder for folder in folders if not folder.startswith(".") and folder not in _SKIP_DIRS
                            and _direct_path(parent / folder))
        seen += 1 + len(folders)
        for filename in sorted(files):
            seen += 1
            if seen > _SCAN_LIMIT:
                return {"paths": candidates, "limited": True}
            path = parent / filename
            if path.suffix.lower() == ".json" and path not in registered and _direct_path(path):
                relative = path.relative_to(registry.parent).as_posix()
                node = _node_at(registry, relative, validator)
                if node and node["id"] not in ids:
                    candidates.append({"path": relative, "id": node["id"]})
        if seen >= _SCAN_LIMIT:
            return {"paths": candidates, "limited": True}
    return {"paths": candidates, "limited": False}


def _direct_path(path):
    try:
        return path.resolve() == path
    except (OSError, RuntimeError):
        return False


def _endpoint_choices(node, variants, source, source_schema):
    endpoints = [node["variants"][name]["endpoints"] for name in variants]
    choices = []
    for endpoint in sorted(set.intersection(*(set(item) for item in endpoints))):
        contexts = []
        for context in source_schema["context"]["enum"]:
            components = []
            for component in source_schema["component"]["enum"]:
                try:
                    for item in endpoints:
                        _address_value(item[endpoint], {"context": context, "component": component})
                except RegistryError:
                    continue
                components.append(component)
            if components:
                contexts.append({"id": context, "components": components})
        if contexts:
            choices.append({"id": endpoint, "contexts": contexts})
    return {"id": source, "endpoints": choices}


def _variants(node, peers, profiles, source_schema):
    result = []
    for name, variant in node["variants"].items():
        dependencies = set(variant.get("dependencies", []))
        selections = [profile["selections"] for profile in profiles.values()
                      if profile["selections"].get(node["id"]) == name]
        sources = []
        for source in sorted(dependencies & peers.keys()):
            peer = peers[source]
            selected = {s.get(source) for s in selections} if selections else set(peer["variants"])
            if selected <= peer["variants"].keys():
                choice = _endpoint_choices(peer, sorted(selected), source, source_schema)
                if choice["endpoints"]:
                    sources.append(choice)
        result.append({"id": name, "execution": variant.get("execution", {}),
                       "dependencies": sorted(peers.keys() - dependencies - {node["id"]}), "sources": sources})
    return result


def complete_registry(project, text, filename, edit=None, *, registry=None):
    """Suggest fields or apply an explicit selection to the in-memory draft."""
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise RegistryError("registry draft exceeds the 2 MiB editor limit")
    selected = registry_path(Path(project).resolve(), registry)
    _, root_text = _document(selected, filename)
    root = _parse_json(root_text if filename else text)
    version = root.get("schemaVersion") if isinstance(root, dict) else None
    if not isinstance(version, str) or version not in SCHEMA_PATHS:
        raise RegistryError("missing or unsupported schemaVersion")
    schema = json.loads(SCHEMA_PATHS[version].read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    # The first selection can fill an absent or empty nodeFiles array.
    root_shape = {**root, "nodeFiles": ["candidate.json"]} if not filename and root.get("nodeFiles", []) == [] else root
    _check_schema(validator.iter_errors(root_shape))
    definitions = schema["$defs"]
    peers = {node["id"]: node for node in root.get("nodes", [])}
    registered = {selected}
    for path in root.get("nodeFiles", []):
        try:
            registered.add(node_file_path(selected, path))
        except RegistryError:
            continue
        if path != filename and (peer := _node_at(selected, path, validator)):
            peers[peer["id"]] = peer
    if not filename:
        if edit is None:
            return _paths(selected, validator, registered, peers.keys())
        path = edit.get("path")
        if not isinstance(path, str) or node_file_path(selected, path) in registered:
            raise RegistryError("select an unregistered node file")
        node = _node_at(selected, path, validator)
        if node is None or node["id"] in peers:
            raise RegistryError("select a valid node file with a new node ID")
        return {"text": _set_field(text, ["nodeFiles"], [*root.get("nodeFiles", []), path])}

    node = _parse_json(text)
    _check_schema(validator.descend(node, definitions["node"]))
    execution = {item["properties"]["type"]["const"]: item for item in definitions["execution"]["oneOf"]}
    injection = definitions["injection"]["properties"]
    variants = _variants(node, peers, root["profiles"], injection["source"]["properties"])
    if edit is None:
        return {"variants": variants, "channels": injection["channel"]["enum"],
                "runners": [{"id": key, "fields": [{"name": name, "array": fields["properties"][name].get("type") == "array"}
                                                   for name in fields["required"] if name != "type"]}
                            for key, fields in execution.items()]}
    variant = next((option for option in variants if option["id"] == edit.get("variant")), None)
    if variant is None:
        raise RegistryError("select a node variant")
    current = node["variants"][variant["id"]]
    field = edit.get("field")
    value = edit.get("value")
    if field == "execution":
        _check_schema(validator.descend(value, definitions[field]))
    elif field == "dependencies" and value in variant["dependencies"]:
        value = [*current[field], value]
    elif field == "injections":
        _check_schema(validator.descend(value, definitions["injection"]))
        source = value["source"]
        allowed = any(node["id"] == source["node"] and endpoint["id"] == source["endpoint"]
                      and context["id"] == source["context"] and source["component"] in context["components"]
                      for node in variant["sources"] for endpoint in node["endpoints"] for context in endpoint["contexts"])
        if not allowed:
            raise RegistryError("select an available dependency endpoint")
        existing = current.get(field, [])
        if any(rule["channel"] == value["channel"] and rule["key"] == value["key"] for rule in existing):
            raise RegistryError("this injection key is already defined for the channel")
        value = [*existing, value]
    else:
        raise RegistryError("select an available completion")
    return {"text": _set_field(text, ["variants", variant["id"], field], value)}
