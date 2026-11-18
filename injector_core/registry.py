"""Read and validate runtime registrations without launching resources."""
from hashlib import sha256
import json
import os
from pathlib import Path, PureWindowsPath
import re

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas/registry-v1.schema.json"
SCHEMA_PATHS = {"1.0": SCHEMA_PATH, "1.1": SCHEMA_PATH.with_name("registry-v1.1.schema.json")}


class RegistryError(ValueError):
    """Invalid registration, with diagnostics that omit configuration values."""


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RegistryError("duplicate JSON property")
        result[key] = value
    return result


def _constant(_value):
    raise RegistryError("non-JSON numeric constant")


def _project_path(root, value, field):
    relative = Path(value.replace("\\", "/"))
    if relative.is_absolute() or PureWindowsPath(value).drive:
        raise RegistryError(f"{field}: expected a project-relative path")
    if not (root / relative).resolve().is_relative_to(root):
        raise RegistryError(f"{field}: path escapes the project root")
    return root / relative


def node_file_path(root, filename):
    field = f"nodeFiles/{filename}"
    try:
        path = _project_path(root, filename, field).resolve()
    except RegistryError:
        raise
    except (OSError, ValueError, RuntimeError) as error:
        raise RegistryError(f"{field}: invalid node file path") from error
    if path == root / "registry.json" or path.suffix.lower() != ".json":
        raise RegistryError(f"{field}: expected a separate JSON file")
    return path


def _validate_references(data, root, profile):
    nodes = {}
    for node in data["nodes"]:
        if node["id"] in nodes:
            raise RegistryError(f"duplicate node ID: {node['id']}")
        nodes[node["id"]] = node

    for node in nodes.values():
        for name in node.get("profileOverrides", {}):
            if name not in data["profiles"]:
                raise RegistryError(f"nodes/{node['id']}/profileOverrides: unknown profile {name}")
        for name, variant in node["variants"].items():
            field = f"nodes/{node['id']}/variants/{name}"
            execution = variant["execution"]
            path_field = {"process": "workingDirectory", "intellij": "projectPath",
                          "compose": "file"}.get(execution["type"])
            if path_field:
                _project_path(root, execution[path_field], f"{field}/execution/{path_field}")
            for dependency in variant["dependencies"]:
                if dependency not in nodes:
                    raise RegistryError(f"{field}: unknown dependency {dependency}")
            for rule in variant.get("injections", []):
                if rule["source"]["node"] not in variant["dependencies"]:
                    raise RegistryError(f"{field}: injection source must be a declared dependency")
                if rule["channel"] == "environment" and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", rule["key"]):
                    raise RegistryError(f"{field}: invalid environment injection key")
            readiness = variant["readiness"]
            if readiness["type"] == "compose":
                if execution["type"] != "compose":
                    raise RegistryError(f"{field}: Compose readiness requires Compose execution")
            else:
                endpoint = variant["endpoints"].get(readiness["endpoint"])
                if endpoint is None:
                    raise RegistryError(f"{field}: unknown readiness endpoint")
                if readiness["type"] == "http" and endpoint["protocol"] not in ("http", "https"):
                    raise RegistryError(f"{field}: HTTP readiness requires an HTTP endpoint")

    profiles = data["profiles"]
    if profile is not None and profile not in profiles:
        raise RegistryError(f"unknown profile: {profile}")
    for name in ([profile] if profile is not None else profiles):
        selected = profiles[name]
        selections = selected["selections"]
        for node_id, variant_name in selections.items():
            if node_id not in nodes:
                raise RegistryError(f"profiles/{name}: unknown selected node {node_id}")
            if variant_name not in nodes[node_id]["variants"]:
                raise RegistryError(f"profiles/{name}: unknown variant for {node_id}")
        for node_id in selected.get("overrides", {}):
            if node_id not in nodes:
                raise RegistryError(f"profiles/{name}: unknown override node {node_id}")
        for target in selected["targets"]:
            if target not in nodes or nodes[target]["kind"] != "application":
                raise RegistryError(f"profiles/{name}: target must name an application")

        pending = list(selected["targets"])
        visited = set()
        while pending:
            node_id = pending.pop()
            if node_id in visited:
                continue
            visited.add(node_id)
            if node_id not in selections:
                raise RegistryError(f"profiles/{name}: missing selection for {node_id}")
            variant = nodes[node_id]["variants"][selections[node_id]]
            pending.extend(variant["dependencies"])
            for rule in variant.get("injections", []):
                source = rule["source"]
                target = source["node"]
                if target not in selections:
                    raise RegistryError(f"profiles/{name}: missing selection for {target}")
                target_variant = nodes[target]["variants"][selections[target]]
                endpoint = target_variant["endpoints"].get(source["endpoint"])
                if endpoint is None:
                    raise RegistryError(f"profiles/{name}/{node_id}: unknown injection endpoint")
                if source["context"] not in endpoint["addresses"]:
                    raise RegistryError(f"profiles/{name}/{node_id}: unknown address context")


def runtime_directory(project, registry=None):
    root = Path(project).resolve()
    if registry is None:
        return root / ".local" / "injector"
    worktree = sha256(os.path.normcase(str(root)).encode("utf-8")).hexdigest()[:24]
    return Path(registry).resolve() / ".local" / "injector" / worktree


def load_registry(project, profile=None, *, registry=None):
    """Read the registry from storage and resolve execution paths against the source."""
    root = Path(project).resolve()
    if registry is not None and not root.is_dir():
        raise RegistryError("source project folder does not exist")
    storage = Path(registry).resolve() if registry is not None else root
    try:
        text = (storage / "registry.json").read_text(encoding="utf-8")
    except OSError as error:
        raise RegistryError("cannot read registry.json; select the folder containing the registry") from error
    except UnicodeError as error:
        raise RegistryError("registry.json must be UTF-8") from error
    return parse_registry(text, root, profile, registry=storage)


def _parse_json(text):
    try:
        return json.loads(text, object_pairs_hook=_object, parse_constant=_constant)
    except json.JSONDecodeError as error:
        raise RegistryError(f"invalid JSON at line {error.lineno}, column {error.colno}") from error
    except RecursionError as error:
        raise RegistryError("registry.json is nested too deeply") from error
    except RegistryError:
        raise
    except ValueError as error:
        raise RegistryError("invalid JSON number") from error


def declared_node_files(text):
    """List referenced files even if a node draft or the root schema is invalid."""
    try:
        data = _parse_json(text)
    except RegistryError:
        return []
    files = data.get("nodeFiles") if isinstance(data, dict) else None
    if not isinstance(files, list):
        return []
    return list(dict.fromkeys(name for name in files if isinstance(name, str) and name))


def _check_schema(errors):
    error = best_match(errors)
    if error is not None:
        pointer = "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1")
                                  for part in error.absolute_path)
        raise RegistryError(f"{pointer}: schema {error.validator} check failed")


def _read_node_file(path):
    try:
        if not path.is_file():
            raise OSError()
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise RegistryError("cannot read node file") from error
    except UnicodeError as error:
        raise RegistryError("node file must be UTF-8") from error


def parse_registry(text, root, profile=None, *, node_draft=None, registry=None):
    """Assemble and validate the registry, optionally using an in-memory node draft."""
    data = _parse_json(text)
    version = data.get("schemaVersion") if isinstance(data, dict) else None
    if not isinstance(version, str) or version not in SCHEMA_PATHS:
        raise RegistryError("missing or unsupported schemaVersion")
    schema = json.loads(SCHEMA_PATHS[version].read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    _check_schema(validator.iter_errors(data))
    files = data.get("nodeFiles", [])
    if node_draft is not None and node_draft[0] not in files:
        raise RegistryError("node file is not declared in registry.json")
    nodes = data.setdefault("nodes", [])
    seen_paths = set()
    for filename in files:
        path = node_file_path(registry if registry is not None else root, filename)
        if path in seen_paths:
            raise RegistryError(f"nodeFiles/{filename}: duplicate node file")
        seen_paths.add(path)
        is_draft = node_draft is not None and filename == node_draft[0]
        try:
            node = _parse_json(node_draft[1] if is_draft else _read_node_file(path))
            _check_schema(validator.descend(node, schema["$defs"]["node"]))
        except RegistryError as error:
            if is_draft:
                raise
            raise RegistryError(f"{filename}: {error}") from error
        nodes.append(node)
    if data.get("nameMappings"):
        from .hostnames import name_mappings
        name_mappings(data)
    _validate_references(data, root, profile)
    return data
