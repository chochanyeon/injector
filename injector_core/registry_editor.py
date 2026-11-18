"""Open, check and replace a project's registry without running its commands."""
from hashlib import sha256
from pathlib import Path
import shutil
import stat
from tempfile import NamedTemporaryFile

from .planning import build_plan
from .registry import RegistryError, declared_node_files, node_file_path, parse_registry
from .runtime import _directory, _lock

MAX_BYTES = 2 * 1024 * 1024


class RegistryConflict(RegistryError):
    """The file no longer matches the version opened by the editor."""


def _file(project):
    root = Path(project).resolve()
    path = root / "registry.json"
    if not stat.S_ISREG(path.lstat().st_mode):
        raise RegistryError("registry.json must be a regular file")
    return path


def _read(path):
    with path.open("rb") as stream:
        content = stream.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise RegistryError(f"{path.name} exceeds the 2 MiB editor limit")
    return content


def _document(root, filename):
    registry = _file(root)
    if not filename:
        return registry, None
    root_text = _read(registry).decode("utf-8")
    if filename not in declared_node_files(root_text):
        raise RegistryError("node file is not declared in registry.json")
    path = node_file_path(root, filename)
    if not path.is_file():
        raise RegistryError(f"{filename}: cannot read node file")
    return path, root_text


def open_registry(project, filename=None):
    root = Path(project).resolve()
    path, root_text = _document(root, filename)
    content = _read(path)
    text = content.decode("utf-8")
    return {"project": str(root), "path": str(path), "files": declared_node_files(root_text if filename else text),
            "text": text, "revision": sha256(content).hexdigest()}


def _validate(root, root_text, filename, text):
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise RegistryError(f"{filename or 'registry.json'} exceeds the 2 MiB editor limit")
    data = parse_registry(root_text, root, node_draft=(filename, text)) if filename else parse_registry(text, root)
    for profile in data["profiles"]:
        try:
            build_plan(data, profile)
        except RegistryError as error:
            raise RegistryError(f"profiles/{profile}: {error}") from error
    return {"schemaVersion": data["schemaVersion"], "nodes": len(data["nodes"]),
            "profiles": len(data["profiles"])}


def validate_registry(project, text, filename=None):
    root = Path(project).resolve()
    _, root_text = _document(root, filename)
    return _validate(root, root_text, filename, text)


def save_registry(project, text, revision, filename=None):
    root = Path(project).resolve()
    content = text.encode("utf-8")
    _file(root)
    with _lock(_directory(root)):
        path, root_text = _document(root, filename)
        original = _read(path)
        name = filename or "registry.json"
        if sha256(original).hexdigest() != revision:
            raise RegistryConflict(f"{name} changed on disk; reopen it before saving")
        summary = _validate(root, root_text, filename, text)
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
                latest, latest_root = _document(root, filename)
                if latest != path or latest_root != root_text or _read(latest) != original:
                    raise RegistryConflict(f"{name} changed on disk; reopen it before saving")
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
    return {**summary, "project": str(root), "files": declared_node_files(root_text if filename else text),
            "revision": sha256(content).hexdigest()}
