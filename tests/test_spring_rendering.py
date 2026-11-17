import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from jsonschema import Draft202012Validator
import yaml

import injector
from injector_core.registry import RegistryError, load_registry
from injector_core.rendering import render_node
from injector_core.resolution import resolve_node

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((ROOT / "examples/spring-config/registry.json").read_text(encoding="utf-8"))


class SpringRenderingTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="injector spring project ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.data = copy.deepcopy(EXAMPLE)
        self.variant = self.data["nodes"][0]["variants"]["real"]

    def render(self, **kwargs):
        return render_node(self.data, self.root, "local", "spring-probe", **kwargs)

    def test_versioned_schema_and_existing_contract_stay_separate(self):
        schema = json.loads((ROOT / "schemas/registry-v1.1.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(self.data)
        (self.root / "registry.json").write_text(json.dumps(self.data), encoding="utf-8")
        self.assertEqual(load_registry(self.root)["schemaVersion"], "1.1")
        self.data["schemaVersion"] = "1.0"
        (self.root / "registry.json").write_text(json.dumps(self.data), encoding="utf-8")
        with self.assertRaises(RegistryError):
            load_registry(self.root)

    def test_yaml_and_intellij_args_are_generated_without_changing_original(self):
        source = self.root / "application-local.yml"
        source.write_text("probe.message: original\n", encoding="utf-8")
        before = source.read_bytes()
        self.variant["vmProperties"]["probe.special"] = 'spaces "quoted" & <xml>'
        result = self.render(environ={"PROBE_SECRET": "never-materialize-this"})
        content = result.yaml_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        self.assertEqual(data["probe.message"], "value-from-generated-yaml")
        self.assertEqual(data["probe.labels"], ["local-a", "local-b"])
        self.assertIsInstance(data["server.port"], int)
        self.assertEqual(data["probe.secret"], "${PROBE_SECRET}")
        self.assertNotIn("never-materialize-this", content + result.run_path.read_text(encoding="utf-8"))
        self.assertEqual(source.read_bytes(), before)
        run = ET.parse(result.run_path).getroot().find("configuration")
        args = run.find("option[@name='VM_PARAMETERS']").attrib["value"]
        self.assertIn("-Dprobe.vm-only=value-from-vm-property", args)
        self.assertIn("-Dspring.config.additional-location=file:", args)
        self.assertIn("%20", args)
        self.assertIn('-Dprobe.special=spaces \\"quoted\\" & <xml>', args)
        self.assertEqual(run.find("module").attrib["name"], "spring-config-probe")

    def test_structured_values_and_per_key_profile_override(self):
        self.variant["springProperties"]["probe.options"] = {"enabled": True, "items": [1, {"name": "한글"}]}
        self.data["profiles"]["local"]["overrides"] = {"spring-probe": {"springProperties": {"probe.message": "profile override"}}}
        result = self.render(environ={})
        content = yaml.safe_load(result.yaml_path.read_text(encoding="utf-8"))
        self.assertEqual(content["probe.options"], {"enabled": True, "items": [1, {"name": "한글"}]})
        self.assertEqual(content["probe.message"], "profile override")
        self.assertIn("overrides/spring-probe", result.settings.origins["springProperties"]["probe.message"])

    def test_spring_injection_uses_dependency_endpoint(self):
        dependency = copy.deepcopy(self.data["nodes"][0])
        dependency["id"] = "catalog"
        self.data["nodes"].append(dependency)
        self.data["profiles"]["local"]["selections"]["catalog"] = "real"
        self.variant["dependencies"] = ["catalog"]
        self.variant["injections"] = [{"channel": "springProperty", "key": "clients.catalog.url",
                                        "source": {"node": "catalog", "endpoint": "http", "context": "host", "component": "url"}}]
        result = self.render(environ={})
        self.assertEqual(yaml.safe_load(result.yaml_path.read_text(encoding="utf-8"))["clients.catalog.url"],
                         "http://127.0.0.1:18090/")

    def test_vm_and_environment_shadows_are_reported(self):
        for channel, key in (("vmProperties", "probe.message"), ("env", "PROBE_MESSAGE")):
            with self.subTest(channel=channel):
                self.variant.setdefault(channel, {})[key] = "shadow"
                with self.assertRaisesRegex(RegistryError, "conflicts"):
                    self.render(environ={})
                del self.variant[channel][key]
        self.assertFalse((self.root / ".local").exists())

    def test_overlapping_and_flattened_keys_are_not_silently_merged(self):
        for entries in ({"probe": {"message": "one"}, "probe.message": "two"},
                        {"probe": {"a.b": 1, "a": {"b": 2}}}):
            with self.subTest(entries=entries):
                self.variant["springProperties"] = entries
                with self.assertRaisesRegex(RegistryError, "overlapping"):
                    self.render(environ={})

    def test_bootstrap_and_existing_additional_location_are_rejected(self):
        self.variant["vmProperties"]["spring.config.additional-location"] = "file:/existing.yml"
        with self.assertRaisesRegex(RegistryError, "conflicts"):
            self.render(environ={})
        del self.variant["vmProperties"]["spring.config.additional-location"]
        self.variant["springProperties"]["spring"] = {"config": {"import": "file:/elsewhere.yml"}}
        with self.assertRaisesRegex(RegistryError, "bootstrap"):
            self.render(environ={})
        self.assertFalse((self.root / ".local").exists())

    def test_runtime_only_references_are_not_copied_into_xml(self):
        self.variant["env"] = {"PASSWORD": {"fromEnv": "PRIVATE_PASSWORD"}}
        with self.assertRaisesRegex(RegistryError, "cannot persist") as result:
            self.render(environ={"PRIVATE_PASSWORD": "secret-not-to-write"})
        self.assertNotIn("secret-not-to-write", str(result.exception))
        self.assertFalse((self.root / ".local").exists())

    def test_unsupported_runner_and_missing_or_outside_project_are_rejected(self):
        original = copy.deepcopy(self.variant["execution"])
        self.variant["execution"] = {"type": "compose", "file": "compose.yaml", "service": "app", "projectName": "sample"}
        with self.assertRaisesRegex(RegistryError, "requires an IntelliJ"):
            self.render(environ={})
        self.variant["execution"] = original
        for path, expected in (("missing-directory", "existing directory inside"), ("..", "escapes the project root")):
            with self.subTest(path=path):
                self.variant["execution"]["projectPath"] = path
                with self.assertRaisesRegex(RegistryError, expected):
                    self.render(environ={})
        self.assertFalse((self.root / ".local").exists())

    def test_two_services_generate_distinct_files(self):
        other = copy.deepcopy(self.data["nodes"][0])
        other["id"] = "other"
        other["variants"]["real"]["springProperties"]["probe.message"] = "other service"
        self.data["nodes"].append(other)
        self.data["profiles"]["local"]["selections"]["other"] = "real"
        first = self.render(environ={})
        second = render_node(self.data, self.root, "local", "other", environ={})
        self.assertNotEqual(first.yaml_path, second.yaml_path)
        self.assertNotEqual(first.run_path, second.run_path)
        self.assertEqual(yaml.safe_load(first.yaml_path.read_text(encoding="utf-8"))["probe.message"], "value-from-generated-yaml")

    def test_unknown_values_are_not_allowed_in_spring_config(self):
        schema = json.loads((ROOT / "schemas/registry-v1.1.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        for value in (None, {"fromEnv": ""}, {"nested": None}):
            with self.subTest(value=value):
                self.variant["springProperties"]["probe.message"] = value
                self.assertFalse(validator.is_valid(self.data))

    def test_composition_can_resolve_spring_references_in_memory(self):
        result = resolve_node(self.data, "local", "spring-probe", {"PROBE_SECRET": "in-memory"})
        self.assertEqual(result.spring_properties["probe.secret"], "in-memory")
        self.assertNotIn("in-memory", json.dumps(result.describe()) + repr(result))

    def test_cli_render_is_redacted_and_does_not_launch(self):
        (self.root / "registry.json").write_text(json.dumps(self.data), encoding="utf-8")
        output = io.StringIO()
        with patch("sys.argv", ["injector.py", "render", "--project", str(self.root),
                                "--profile", "local", "--node", "spring-probe"]), \
                patch.dict("os.environ", {"PROBE_SECRET": "no-secret-on-console"}), \
                patch("subprocess.run") as launch, contextlib.redirect_stdout(output):
            injector.main()
        launch.assert_not_called()
        self.assertNotIn("no-secret-on-console", output.getvalue())
        self.assertTrue(Path(json.loads(output.getvalue())["springConfig"]).is_file())


if __name__ == "__main__":
    unittest.main()
