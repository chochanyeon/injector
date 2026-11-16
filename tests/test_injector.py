import json
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import injector


class ConfigurationTest(unittest.TestCase):
    def test_vault_mock_is_opt_in_and_uses_runtime_specific_addresses(self):
        _, _, normal, _ = injector.resolve("mock")
        self.assertNotIn("VAULT_ADDR", normal)
        self.assertEqual(injector.resolve("mock", True)[2]["VAULT_PATH"], "secret/data/orders")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(injector, "DEMO", root):
                path = injector.generate("mock", with_vault=True, vault_service="payments")
            run = ET.parse(path).getroot().find("configuration")
            env = {item.attrib["name"]: item.attrib["value"] for item in run.find("envs")}
            self.assertEqual(env["VAULT_ADDR"], "http://localhost:18083")
            main = json.loads((root / ".local/compose-mock.json").read_text(encoding="utf-8"))["services"]["main"]
            self.assertEqual(main["environment"]["VAULT_ADDR"], "http://vault-mock:8080")
            self.assertEqual(env["VAULT_PATH"], "secret/data/payments")
            self.assertEqual(main["environment"]["VAULT_PATH"], env["VAULT_PATH"])

    def test_vault_service_name_cannot_be_a_path_or_empty(self):
        for name in ("", "../orders", "orders/payments", "Orders", "orders?version=1", "orders\n"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                injector.resolve("mock", True, name)

    def test_up_with_vault_starts_the_mock_service(self):
        with patch("sys.argv", ["injector.py", "up", "--with-vault"]), \
                patch.object(injector, "generate") as generate, patch.object(injector, "compose") as compose, \
                contextlib.redirect_stdout(io.StringIO()):
            injector.main()
        generate.assert_called_once_with("mock", True, None)
        self.assertIn("vault-mock", compose.call_args.args)
        output = io.StringIO()
        with patch("sys.argv", ["injector.py", "plan", "--with-vault"]), contextlib.redirect_stdout(output):
            injector.main()
        self.assertEqual(json.loads(output.getvalue())["auxiliaryServices"], ["vault-mock"])

    def test_profiles_switch_dependency_and_keep_common_values(self):
        for profile, dependency, port in [("mock", "wiremock", "18081"), ("real", "catalog", "18082")]:
            with self.subTest(profile=profile):
                _, actual, env, options = injector.resolve(profile)
                self.assertEqual(actual, dependency)
                self.assertEqual(env["CATALOG_URL"], f"http://localhost:{port}")
                self.assertEqual(env["DEMO_MESSAGE"], "environment injected")
                self.assertIn(f"-Dinjector.profile={profile}", options)

    def test_generated_ide_and_container_configs_have_same_injection(self):
        config = json.loads(injector.CONFIG.read_text(encoding="utf-8"))
        config["profiles"]["mock"]["env"]["DEMO_MESSAGE"] = '한글 & <xml> "quotes"'
        config["profiles"]["mock"]["vmOptions"].append("-Dsample.message=hello world")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "project.json"
            source.write_text(json.dumps(config), encoding="utf-8")
            with patch.object(injector, "DEMO", root), patch.object(injector, "CONFIG", source):
                path = injector.generate("mock")
            self.assertEqual(path, root / ".run/Injector-mock.run.xml")
            run = ET.parse(path).getroot().find("configuration")
            env = {item.attrib["name"]: item.attrib["value"] for item in run.find("envs")}
            self.assertEqual(env["DEMO_MESSAGE"], '한글 & <xml> "quotes"')
            vm = run.find("option[@name='VM_PARAMETERS']").attrib["value"]
            self.assertIn('"-Dsample.message=hello world"', vm)
            override = json.loads((root / ".local/compose-mock.json").read_text(encoding="utf-8"))
            main = override["services"]["main"]
            self.assertEqual(main["environment"]["DEMO_MESSAGE"], env["DEMO_MESSAGE"])
            self.assertEqual(main["environment"]["CATALOG_URL"], "http://wiremock:8080")
            self.assertIn("-Dsample.message=hello world", main["command"])


if __name__ == "__main__":
    unittest.main()
