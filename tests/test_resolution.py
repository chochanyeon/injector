import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import injector
from injector_core.registry import RegistryError
from injector_core.resolution import resolve_node

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((ROOT / "examples/registry/registry.json").read_text(encoding="utf-8"))


class ResolutionTest(unittest.TestCase):
    def setUp(self):
        self.data = copy.deepcopy(EXAMPLE)
        self.environment = {"LOCAL_DB_PASSWORD": "secret fixture value"}

    def resolve(self, node="orders", profile="local-real"):
        return resolve_node(self.data, profile, node, self.environment)

    def test_host_container_and_mock_addresses_follow_selected_variant(self):
        self.assertEqual(self.resolve().env["CATALOG_URL"], "http://catalog.local.test.com:18082/")
        self.assertEqual(self.resolve(profile="local-mock").env["CATALOG_URL"],
                         "http://catalog.local.test.com:18081/")
        self.assertEqual(self.resolve("catalog").env["DB_HOST"], "database")
        self.assertEqual(self.resolve().env["DB_HOST"], "127.0.0.1")

    def test_setting_precedence_and_final_provenance(self):
        self.data["defaults"]["env"]["MESSAGE"] = "common"
        variant = self.data["nodes"][0]["variants"]["real"]
        variant["env"]["MESSAGE"] = "variant"
        variant["vmOptions"] = ["-ea"]
        self.data["profiles"]["local-real"]["overrides"] = {
            "orders": {"env": {"MESSAGE": "개인 값 & <xml>\nnext"},
                       "vmProperties": {"message": "spaces and quotes \"hello\""},
                       "vmOptions": ["-Xss1m"]}}
        result = self.resolve()
        self.assertEqual(result.env["MESSAGE"], "개인 값 & <xml>\nnext")
        self.assertEqual(result.vm_options, ["-Xmx256m", "-ea", "-Xss1m"])
        self.assertIn('-Dmessage=spaces and quotes "hello"', result.jvm_arguments())
        self.assertEqual(result.origins["env"]["MESSAGE"], "profiles/local-real/overrides/orders/env/MESSAGE")

    def test_missing_reference_fails_but_shadowed_reference_is_not_read(self):
        self.environment.clear()
        with self.assertRaisesRegex(RegistryError, "required environment reference"):
            self.resolve()
        self.data["profiles"]["local-real"]["overrides"] = {"orders": {"env": {"DB_PASSWORD": "local"}}}
        self.assertEqual(self.resolve().env["DB_PASSWORD"], "local")

    def test_injection_conflict_with_manual_or_duplicate_value_is_rejected(self):
        self.data["defaults"]["env"]["CATALOG_URL"] = "manual"
        with self.assertRaisesRegex(RegistryError, "injection conflicts"):
            self.resolve()
        del self.data["defaults"]["env"]["CATALOG_URL"]
        rules = self.data["nodes"][0]["variants"]["real"]["injections"]
        rules.append(copy.deepcopy(rules[0]))
        with self.assertRaisesRegex(RegistryError, "injection conflicts"):
            self.resolve()

    def test_vm_property_injection_and_port_are_single_jvm_arguments(self):
        rule = self.data["nodes"][0]["variants"]["real"]["injections"][0]
        rule.update(channel="vmProperty", key="catalog.port")
        rule["source"]["component"] = "port"
        self.assertIn("-Dcatalog.port=18082", self.resolve().jvm_arguments())

    def test_invalid_vm_property_key_is_rejected_for_manual_and_injected_values(self):
        self.data["defaults"]["vmProperties"] = {"bad=key": "value"}
        with self.assertRaisesRegex(RegistryError, "invalid VM property key"):
            self.resolve()
        del self.data["defaults"]["vmProperties"]
        self.data["nodes"][0]["variants"]["real"]["injections"][0].update(channel="vmProperty", key="bad=key")
        with self.assertRaisesRegex(RegistryError, "invalid VM property key"):
            self.resolve()

    def test_ipv6_authority_and_url_path_encoding(self):
        address = self.data["nodes"][1]["variants"]["real"]["endpoints"]["http"]["addresses"]["host"]
        address.update(host="::1", path="/한글/a b")
        self.assertEqual(self.resolve().env["CATALOG_URL"], "http://[::1]:18082/%ED%95%9C%EA%B8%80/a%20b")

    def test_bind_wildcards_are_not_callable_addresses(self):
        address = self.data["nodes"][1]["variants"]["real"]["endpoints"]["http"]["addresses"]["host"]
        for host in ("0.0.0.0", "::", "*", "host..", "user:password@host", "http://host"):
            with self.subTest(host=host):
                address["host"] = host
                with self.assertRaises(RegistryError):
                    self.resolve()

    def test_url_requires_scheme_and_does_not_accept_query_as_path(self):
        address = self.data["nodes"][1]["variants"]["real"]["endpoints"]["http"]["addresses"]["host"]
        for change in ({"scheme": ""}, {"scheme": "https"}, {"path": "/a?token=value"}, {"path": "/a#fragment"}):
            with self.subTest(change=change):
                previous = dict(address)
                address.update(change)
                with self.assertRaises(RegistryError):
                    self.resolve()
                address.clear()
                address.update(previous)

    def test_null_character_cannot_reach_runtime_settings(self):
        self.environment["LOCAL_DB_PASSWORD"] = "unsafe\x00value"
        with self.assertRaisesRegex(RegistryError, "null character"):
            self.resolve()

    def test_public_output_and_repr_hide_all_values(self):
        self.data["defaults"]["vmOptions"] = ["-XX:Example=hidden-option"]
        self.data["defaults"]["vmProperties"] = {"literal.password": "hidden-literal"}
        result = self.resolve()
        rendered = json.dumps(result.describe()) + repr(result)
        for value in ("secret fixture value", "hidden-literal", "hidden-option"):
            self.assertNotIn(value, rendered)
        self.assertIn("via environment/LOCAL_DB_PASSWORD", result.origins["env"]["DB_PASSWORD"])

    def test_resolution_does_not_mutate_registry(self):
        before = copy.deepcopy(self.data)
        self.resolve()
        self.assertEqual(self.data, before)

    def test_cli_resolve_is_redacted_and_does_not_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "registry.json").write_text(json.dumps(self.data), encoding="utf-8")
            output = io.StringIO()
            with patch("sys.argv", ["injector.py", "resolve", "--project", directory,
                                    "--profile", "local-real", "--node", "orders"]), \
                    patch.dict("os.environ", self.environment), patch("subprocess.run") as execute, \
                    contextlib.redirect_stdout(output):
                injector.main()
            execute.assert_not_called()
            self.assertNotIn("secret fixture value", output.getvalue())
            self.assertEqual(json.loads(output.getvalue())["env"]["DB_PASSWORD"]["value"], "<redacted>")


if __name__ == "__main__":
    unittest.main()
