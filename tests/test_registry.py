import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import injector
from injector_core.registry import RegistryError, load_registry

EXAMPLE = json.loads((Path(__file__).resolve().parents[1] / "examples/registry/registry.json")
                     .read_text(encoding="utf-8"))


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="injector project ")
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name)
        self.data = copy.deepcopy(EXAMPLE)

    def load(self, profile=None):
        (self.project / "registry.json").write_text(json.dumps(self.data), encoding="utf-8")
        return load_registry(self.project, profile)

    def test_loads_external_project_in_space_path_without_resolving_secrets(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.load(), self.data)

    def test_another_project_and_profile_are_independent_of_demo(self):
        variant = copy.deepcopy(self.data["nodes"][0]["variants"]["real"])
        variant.update(execution={"type": "external"}, dependencies=[], injections=[])
        self.data = {"schemaVersion": "1.0", "nodes": [
            {"id": "another", "kind": "application", "variants": {"existing": variant}}],
            "profiles": {"independent": {"targets": ["another"], "selections": {"another": "existing"}}}}
        self.load()
        previous = Path.cwd()
        try:
            os.chdir(self.project.parent)
            self.assertEqual(load_registry(self.project.name)["profiles"], self.data["profiles"])
        finally:
            os.chdir(previous)

    def test_duplicate_node_ids_are_rejected(self):
        self.data["nodes"].append(copy.deepcopy(self.data["nodes"][0]))
        with self.assertRaisesRegex(RegistryError, "duplicate node ID"):
            self.load()

    def test_missing_dependency_is_rejected(self):
        self.data["nodes"][0]["variants"]["real"]["dependencies"].append("missing")
        with self.assertRaisesRegex(RegistryError, "unknown dependency"):
            self.load()

    def test_unknown_node_variant_override_and_target_are_rejected(self):
        for change, message in (
            (lambda p: p["selections"].update(missing="real"), "unknown selected node"),
            (lambda p: p["selections"].update(catalog="missing"), "unknown variant"),
            (lambda p: p.update(overrides={"missing": {}}), "unknown override node"),
            (lambda p: p.update(targets=["database"]), "target must name an application"),
        ):
            with self.subTest(message=message):
                self.data = copy.deepcopy(EXAMPLE)
                change(self.data["profiles"]["local-real"])
                with self.assertRaisesRegex(RegistryError, message):
                    self.load()

    def test_selected_profile_limits_profile_dependent_checks(self):
        del self.data["profiles"]["local-real"]["selections"]["catalog"]
        self.load("local-mock")
        with self.assertRaisesRegex(RegistryError, "missing selection"):
            self.load()
        with self.assertRaisesRegex(RegistryError, "unknown profile"):
            self.load("absent")

    def test_injection_requires_declared_dependency(self):
        rule = self.data["nodes"][1]["variants"]["real"]["injections"][0]
        rule["source"]["node"] = "orders"
        with self.assertRaisesRegex(RegistryError, "declared dependency"):
            self.load()

    def test_selected_endpoint_and_context_must_exist(self):
        source = self.data["nodes"][0]["variants"]["real"]["injections"][0]["source"]
        source["endpoint"] = "missing"
        with self.assertRaisesRegex(RegistryError, "unknown injection endpoint"):
            self.load()
        source["endpoint"] = "http"
        del self.data["nodes"][1]["variants"]["real"]["endpoints"]["http"]["addresses"]["host"]
        with self.assertRaisesRegex(RegistryError, "unknown address context"):
            self.load()

    def test_readiness_matches_endpoint_and_execution(self):
        for readiness, message in (
            ({"type": "tcp", "endpoint": "missing", "timeoutSeconds": 3}, "unknown readiness endpoint"),
            ({"type": "compose", "timeoutSeconds": 3}, "requires Compose execution"),
        ):
            with self.subTest(message=message):
                self.data["nodes"][0]["variants"]["real"]["readiness"] = readiness
                with self.assertRaisesRegex(RegistryError, message):
                    self.load()

    def test_project_paths_cannot_escape_root(self):
        for value in ("../outside", "/outside", "C:\\outside", "C:outside", "\\\\server\\share"):
            with self.subTest(path=value):
                self.data["nodes"][0]["variants"]["real"]["execution"]["projectPath"] = value
                with self.assertRaisesRegex(RegistryError, "path"):
                    self.load()

    def test_cycles_are_representable_but_not_planned_or_launched(self):
        self.data["nodes"][2]["variants"]["real"]["dependencies"] = ["orders"]
        self.assertEqual(self.load(), self.data)

    def test_bad_json_duplicate_properties_and_non_json_constants(self):
        for raw, message in (("{", "invalid JSON"),
                             ('{"nodes":[],"nodes":[]}', "duplicate JSON property"),
                             ('{"value":NaN}', "non-JSON numeric constant")):
            with self.subTest(message=message):
                (self.project / "registry.json").write_text(raw, encoding="utf-8")
                with self.assertRaisesRegex(RegistryError, message):
                    load_registry(self.project)

    def test_schema_diagnostics_omit_values(self):
        self.data["defaults"]["env"]["SECRET_VALUE"] = {"unexpected": "do-not-print-this-value"}
        with self.assertRaises(RegistryError) as result:
            self.load()
        self.assertNotIn("do-not-print-this-value", str(result.exception))
        self.assertIn("schema", str(result.exception))
        output = io.StringIO()
        with patch("sys.argv", ["injector.py", "validate", "--project", str(self.project)]), \
                contextlib.redirect_stderr(output), self.assertRaises(SystemExit) as exit_result:
            injector.main()
        self.assertEqual(exit_result.exception.code, 1)
        self.assertNotIn("do-not-print-this-value", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())

    def test_cli_validation_neither_launches_resources_nor_generates_files(self):
        self.load()
        before = list(self.project.iterdir())
        output = io.StringIO()
        with patch("sys.argv", ["injector.py", "validate", "--project", str(self.project)]), \
                patch("subprocess.run") as execute, patch.object(injector, "generate") as generate, \
                contextlib.redirect_stdout(output):
            injector.main()
        execute.assert_not_called()
        generate.assert_not_called()
        self.assertEqual(list(self.project.iterdir()), before)
        self.assertEqual(json.loads(output.getvalue())["status"], "valid")
        self.assertNotIn("LOCAL_DB_PASSWORD", output.getvalue())

    def test_cli_rejects_execution_options_and_legacy_project_switch(self):
        for arguments in (["validate", "--project", str(self.project), "--main-docker"],
                          ["validate", "--project", str(self.project), "--with-vault"],
                          ["validate"], ["up", "--project", str(self.project)]):
            with self.subTest(arguments=arguments), patch("sys.argv", ["injector.py", *arguments]), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
                injector.main()
            self.assertEqual(result.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
