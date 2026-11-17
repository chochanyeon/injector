"""Validate local name mappings and manage explicitly owned hosts entries."""
from hashlib import sha256
from ipaddress import ip_address
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory

from .registry import RegistryError

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_BOM = b"\xef\xbb\xbf"


def _hostname(value):
    return value.removesuffix(".").lower()


def name_mappings(data):
    result = {}
    for index, entry in enumerate(data.get("nameMappings", [])):
        field = f"nameMappings/{index}"
        host = _hostname(entry["hostname"])
        if (not entry["hostname"].isascii() or len(host) > 253
                or not re.fullmatch(rf"(?:{_LABEL}\.)*{_LABEL}", host)
                or host.rsplit(".", 1)[-1].isdigit()):
            raise RegistryError(f"{field}: expected an ASCII DNS hostname")
        if host in result:
            raise RegistryError(f"{field}: duplicate hostname")
        try:
            address = ip_address(entry["address"])
        except ValueError as error:
            raise RegistryError(f"{field}: expected an IP address") from error
        if "%" in str(address) or address.is_unspecified or address.is_multicast:
            raise RegistryError(f"{field}: expected a concrete unscoped IP address")
        if entry["method"] == "hosts" and (
                not address.is_loopback or "." not in host or host.endswith(".localhost")):
            raise RegistryError(f"{field}: managed hosts entries need a custom DNS domain and a loopback IP")
        result[host] = (address, entry["method"])
    return result


def check_resolution(data, variants, project):
    mappings = name_mappings(data)
    if not mappings:
        return
    selected = {
        _hostname(address["host"])
        for variant in variants
        for endpoint in variant["endpoints"].values()
        if (address := endpoint["addresses"].get("host"))
    }
    for hostname, (expected, method) in mappings.items():
        if hostname not in selected:
            continue
        if method == "hosts":
            content = hosts_path().read_bytes()
            _, changes = plan_hosts(content, {hostname: (expected, method)}, project)
            if changes["add"]:
                raise RegistryError(f"{hostname}: apply the project hosts mapping before prepare")
        try:
            actual = {ip_address(item[4][0]) for item in socket.getaddrinfo(hostname, None)}
        except socket.gaierror:
            actual = set()
        if actual != {expected}:
            raise RegistryError(f"{hostname}: expected to resolve only to {expected}; check {method} mapping")


def hosts_path():
    if os.name == "nt":
        return Path(os.environ["SystemRoot"]) / "System32/drivers/etc/hosts"
    return Path("/etc/hosts")


def _marker(project):
    path = os.path.normcase(str(Path(project).resolve()))
    return b" # injector:" + sha256(path.encode()).hexdigest()[:24].encode("ascii")


def plan_hosts(content, mappings, project):
    """Return proposed bytes and a diff limited to the project's own entries."""
    marker = _marker(project)
    bom = _BOM if content.startswith(_BOM) else b""
    payload = content.removeprefix(bom)
    if b"\0" in payload:
        raise RegistryError("unsupported hosts file encoding")
    preserved, owned = [], []
    existing = {}
    for line in payload.splitlines(keepends=True):
        fields = line.split(b"#", 1)[0].split()
        owned_line = line.rstrip(b"\r\n")
        if (owned_line.endswith(marker) and len(fields) == 2
                and b"#" not in owned_line[:-len(marker)]):
            owned.append(owned_line)
            continue
        preserved.append(line)
        if len(fields) >= 2:
            for key in fields[1:]:
                existing.setdefault(key.lower().removesuffix(b"."), []).append(
                    (fields[0], b"# injector:" in line))

    desired, reused = [], []
    for host, (address, method) in mappings.items():
        if method != "hosts":
            continue
        key = host.encode("ascii")
        current = existing.get(key, [])
        if current:
            for value, managed in current:
                try:
                    matches = ip_address(value.decode("ascii")) == address
                except ValueError:
                    matches = False
                if managed or not matches:
                    raise RegistryError(f"{host}: conflicting hosts entry; existing entries were preserved")
            reused.append(host)
            continue
        desired.append(str(address).encode("ascii") + b"\t" + key + marker)

    newline = b"\r\n" if b"\r\n" in payload else b"\n"
    result = content if owned == desired else bom + b"".join(line + newline for line in desired) + b"".join(preserved)
    return result, {
        "add": [line.decode("ascii") for line in desired if line not in owned],
        "remove": [line.decode("ascii", errors="replace") for line in owned if line not in desired],
        "reuse": reused,
    }


def _replace_windows(path, original, content):
    import ctypes
    from ctypes import wintypes

    replace = ctypes.WinDLL("kernel32", use_last_error=True).ReplaceFileW
    replace.argtypes = [wintypes.LPCWSTR] * 3 + [wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID]
    replace.restype = wintypes.BOOL
    with NamedTemporaryFile(dir=path.parent, prefix="injector-hosts-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
    backup = temporary.with_suffix(".bak")
    try:
        if path.read_bytes() != original:
            raise RegistryError("hosts changed during the operation; retry after reviewing the preview")
        if not replace(str(path), str(temporary), str(backup), 0, None, None):
            code = ctypes.get_last_error()
            if backup.exists():
                raise RegistryError(f"hosts replacement failed; recovery copy: {backup}")
            raise ctypes.WinError(code)
        backup.unlink(missing_ok=True)
    finally:
        temporary.unlink(missing_ok=True)


def _replace_macos(path, original, content):
    with TemporaryDirectory(dir=path.parent, prefix="injector-hosts-") as directory:
        temporary = Path(directory) / "hosts"
        # macOS cp -p preserves ownership, permissions, flags and ACLs.
        copied = subprocess.run(["/bin/cp", "-p", str(path), str(temporary)], capture_output=True)
        if copied.returncode:
            raise RegistryError("could not copy hosts file and its permissions")
        temporary.write_bytes(content)
        if path.is_symlink() or path.read_bytes() != original:
            raise RegistryError("hosts changed during the operation; retry after reviewing the preview")
        current, replacement = path.stat(), temporary.stat()
        if (current.st_mode, current.st_uid, current.st_gid) != (
                replacement.st_mode, replacement.st_uid, replacement.st_gid):
            raise RegistryError("could not preserve hosts file ownership and permissions")
        temporary.replace(path)


def manage_hosts(project, mappings, action):
    path = hosts_path()
    if action == "preview":
        _, changes = plan_hosts(path.read_bytes(), mappings, project)
        return {"path": str(path), **changes}
    if os.name != "nt" and sys.platform != "darwin":
        raise RegistryError("hosts apply/remove currently support macOS and Windows")

    try:
        with (path.parent / "injector-hosts.lock").open("a+b") as lock:
            lock.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise RegistryError("another Injector hosts operation is running") from error
            if path.is_symlink():
                raise RegistryError("hosts file must not be a symbolic link")
            original = path.read_bytes()
            content, changes = plan_hosts(original, mappings, project)
            if content != original:
                replace = _replace_windows if os.name == "nt" else _replace_macos
                replace(path, original, content)
    except PermissionError as error:
        instructions = "an Administrator terminal" if os.name == "nt" else "sudo on macOS"
        raise RegistryError(f"hosts apply/remove requires {instructions}") from error
    return {"path": str(path), **changes}
