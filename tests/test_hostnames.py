from ipaddress import ip_address
import json
from pathlib import Path
import os
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from injector_core.hostnames import manage_hosts, name_mappings, plan_hosts
from injector_core.registry import RegistryError
from injector_core.runtime import prepare
from test_runtime import fixture, write_registry


class HostsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / "hosts"
        self.hostname = "service.injector.test"
        self.loopback = ip_address("127.0.0.1")
        self.mappings = {self.hostname: (self.loopback, "hosts")}

    def test_existing_match_is_reused_and_never_removed(self):
        original = b"127.0.0.1  SERVICE.injector.test another.test # user\r\n"
        content, changes = plan_hosts(original, self.mappings, self.root)
        self.assertEqual(content, original)
        self.assertEqual(changes, {"add": [], "remove": [], "reuse": [self.hostname]})
        self.assertEqual(plan_hosts(content, {}, self.root)[0], original)

    def test_preserves_conflicting_user_and_other_project_entries(self):
        other, _ = plan_hosts(b"", self.mappings, self.root / "different")
        conflicting = b"127.0.0.2 localhost service.injector.test. # user\n"
        for content in (other, conflicting):
            with self.subTest(content=content), self.assertRaisesRegex(RegistryError, "conflicting hosts"):
                plan_hosts(content, self.mappings, self.root)

    @unittest.skipUnless(os.name == "nt" or sys.platform == "darwin", "macOS or Windows")
    def test_preview_apply_and_remove_preserve_original_bytes(self):
        original = b"\xef\xbb\xbf# original\r\n127.0.0.2 another.test"
        self.path.write_bytes(original)
        if sys.platform == "darwin":
            self.path.chmod(0o640)
        with patch("injector_core.hostnames.hosts_path", return_value=self.path):
            self.assertEqual(len(manage_hosts(self.root, self.mappings, "preview")["add"]), 1)
            self.assertEqual(self.path.read_bytes(), original)
            manage_hosts(self.root, self.mappings, "apply")
            self.assertIn(self.hostname.encode(), self.path.read_bytes())
            self.assertEqual(manage_hosts(self.root, self.mappings, "apply")["add"], [])
            with self.path.open("ab") as stream:
                stream.write(b"\r\n# user edited later")
            manage_hosts(self.root, {}, "remove")
        self.assertEqual(self.path.read_bytes(), original + b"\r\n# user edited later")
        if sys.platform == "darwin":
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)

    def test_rejects_invalid_mappings_and_case_insensitive_duplicate(self):
        good = {"hostname": self.hostname, "address": "127.0.0.1", "method": "hosts"}
        for invalid in (
            [{**good, "hostname": "bad\n127.0.0.1 injected.test"}],
            [{**good, "address": "10.0.0.1"}],
            [good, {**good, "hostname": self.hostname.upper() + "."}],
        ):
            with self.subTest(invalid=invalid), self.assertRaises(RegistryError):
                name_mappings({"nameMappings": invalid})
        external = {"hostname": "localhost", "address": "::1", "method": "external"}
        self.assertEqual(name_mappings({"nameMappings": [external]}), {"localhost": (ip_address("::1"), "external")})

    def test_prepare_checks_selected_resolution_before_stopping_previous_session(self):
        data = fixture(self.root)
        main = data["nodes"][0]["variants"]["local"]
        main["endpoints"]["http"]["addresses"]["host"]["host"] = self.hostname
        data["nameMappings"] = [
            {"hostname": self.hostname, "address": str(self.loopback), "method": "external"},
            {"hostname": "unused.injector.test", "address": "::1", "method": "external"},
        ]
        write_registry(self.root, data)
        manifest = self.root / ".local/injector/session.json"
        manifest.parent.mkdir(parents=True)
        previous = {"id": "previous", "resources": []}
        manifest.write_text(json.dumps(previous))
        with patch("injector_core.hostnames.socket.getaddrinfo", return_value=[
            (None, None, None, "", ("127.0.0.1", 0)),
            (None, None, None, "", ("127.0.0.2", 0)),
        ]) as lookup:
            with self.assertRaisesRegex(RegistryError, "expected to resolve only"):
                prepare(self.root, "main", mode="dummy")
        lookup.assert_called_once_with(self.hostname, None)
        self.assertEqual(json.loads(manifest.read_text()), previous)
