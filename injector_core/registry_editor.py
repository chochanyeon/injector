"""Open, check and replace a project's registry without running its commands."""
from hashlib import sha256
from pathlib import Path
import shutil
import stat
from tempfile import NamedTemporaryFile

from .planning import build_plan
from .registry import RegistryError, parse_registry
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
        raise RegistryError("registry.json exceeds the 2 MiB editor limit")
    return content


def open_registry(project):
    path = _file(project)
    content = _read(path)
    return {"project": str(path.parent), "path": str(path),
            "text": content.decode("utf-8"), "revision": sha256(content).hexdigest()}


def validate_registry(project, text):
    root = _file(project).parent
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise RegistryError("registry.json exceeds the 2 MiB editor limit")
    data = parse_registry(text, root)
    for profile in data["profiles"]:
        try:
            build_plan(data, profile)
        except RegistryError as error:
            raise RegistryError(f"profiles/{profile}: {error}") from error
    return {"schemaVersion": data["schemaVersion"], "nodes": len(data["nodes"]),
            "profiles": len(data["profiles"])}


def save_registry(project, text, revision):
    summary = validate_registry(project, text)
    content = text.encode("utf-8")
    path = _file(project)
    with _lock(_directory(path.parent)):
        original = _read(_file(path.parent))
        if sha256(original).hexdigest() != revision:
            raise RegistryConflict("registry.json changed on disk; reopen it before saving")
        if b"\r" not in content and b"\r\n" in original and b"\n" not in original.replace(b"\r\n", b""):
            content = content.replace(b"\n", b"\r\n")
            if len(content) > MAX_BYTES:
                raise RegistryError("registry.json exceeds the 2 MiB editor limit")
        if original != content:
            with NamedTemporaryFile(dir=path.parent, prefix=".injector-registry-", delete=False) as stream:
                temporary = Path(stream.name)
            try:
                temporary.write_bytes(content)
                shutil.copymode(path, temporary)
                if _read(_file(path.parent)) != original:
                    raise RegistryConflict("registry.json changed on disk; reopen it before saving")
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
    return {**summary, "project": str(path.parent), "revision": sha256(content).hexdigest()}
