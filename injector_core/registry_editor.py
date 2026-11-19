"""Open, check and replace a project's registry without running its commands."""
from hashlib import sha256
from pathlib import Path
import shutil
import stat
from tempfile import NamedTemporaryFile

from .planning import validate_plans
from .registry import RegistryError, declared_node_files, node_file_path, parse_registry, registry_path
from .runtime import _directory, _lock

MAX_BYTES = 2 * 1024 * 1024


class RegistryConflict(RegistryError):
    """The file no longer matches the version opened by the editor."""


def _require_regular_file(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise RegistryError("registry must be a regular file")


def _read(path):
    with path.open("rb") as stream:
        content = stream.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise RegistryError(f"{path.name} exceeds the 2 MiB editor limit")
    return content


def _document(registry, filename):
    _require_regular_file(registry)
    if not filename:
        return registry, None
    root_text = _read(registry).decode("utf-8")
    if filename not in declared_node_files(root_text):
        raise RegistryError("node file is not declared in the registry")
    path = node_file_path(registry, filename)
    if not path.is_file():
        raise RegistryError(f"{filename}: cannot read node file")
    return path, root_text


def open_registry(project, filename=None, *, registry=None):
    root = Path(project).resolve()
    selected = registry_path(root, registry)
    path, root_text = _document(selected, filename)
    content = _read(path)
    text = content.decode("utf-8")
    return {"project": str(root), "registry": str(selected) if registry is not None else "",
            "path": str(path), "files": declared_node_files(root_text if filename else text),
            "text": text, "revision": sha256(content).hexdigest()}


def _validate(root, registry, root_text, filename, text):
    if not root.is_dir():
        raise RegistryError("source project folder does not exist")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise RegistryError(f"{filename or registry.name} exceeds the 2 MiB editor limit")
    data = (parse_registry(root_text, root, registry, node_draft=(filename, text))
            if filename else parse_registry(text, root, registry))
    validate_plans(data)
    return {"schemaVersion": data["schemaVersion"], "nodes": len(data["nodes"]),
            "profiles": len(data["profiles"])}


def validate_registry(project, text, filename=None, *, registry=None):
    root = Path(project).resolve()
    selected = registry_path(root, registry)
    _, root_text = _document(selected, filename)
    return _validate(root, selected, root_text, filename, text)


def save_registry(project, text, revision, filename=None, *, registry=None):
    root = Path(project).resolve()
    selected = registry_path(root, registry)
    content = text.encode("utf-8")
    _require_regular_file(selected)
    with _lock(_directory(selected.parent)):
        path, root_text = _document(selected, filename)
        original = _read(path)
        name = filename or selected.name
        if sha256(original).hexdigest() != revision:
            raise RegistryConflict(f"{name} changed on disk; reopen it before saving")
        summary = _validate(root, selected, root_text, filename, text)
        if b"\r" not in content and b"\r\n" in original and b"\n" not in original.replace(b"\r\n", b""):
            content = content.replace(b"\n", b"\r\n")
            if len(content) > MAX_BYTES:
                raise RegistryError(f"{name} exceeds the 2 MiB editor limit")
        if original != content:
            with NamedTemporaryFile(dir=path.parent, prefix=".injector-registry-", delete=False) as stream:
                temporary = Path(stream.name)
            try:
                temporary.write_bytes(content)
                shutil.copymode(path, temporary)
                latest, latest_root = _document(selected, filename)
                if latest != path or latest_root != root_text or _read(latest) != original:
                    raise RegistryConflict(f"{name} changed on disk; reopen it before saving")
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
    return {**summary, "project": str(root), "registry": str(selected) if registry is not None else "",
            "files": declared_node_files(root_text if filename else text),
            "revision": sha256(content).hexdigest()}
