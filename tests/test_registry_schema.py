import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/registry-v1.schema.json").read_text(encoding="utf-8"))
EXAMPLE = json.loads((ROOT / "examples/registry/registry.json").read_text(encoding="utf-8"))


class RegistrySchemaTest(unittest.TestCase):
    def setUp(self):
        self.validator = Draft202012Validator(SCHEMA)
        self.registry = copy.deepcopy(EXAMPLE)

    def test_schema_and_multi_app_example_are_valid(self):
        Draft202012Validator.check_schema(SCHEMA)
        self.validator.validate(self.registry)

    def test_draft_and_legacy_config_are_not_runtime_registries(self):
        for relative in ("examples/demo/config/project.json",
                         "skills/injector-register-monorepo/assets/registration-draft.example.json"):
            with self.subTest(path=relative):
                value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
                self.assertFalse(self.validator.is_valid(value))

    def test_unrecognized_version_and_fields_are_rejected(self):
        self.registry["schemaVersion"] = "2.0"
        self.assertFalse(self.validator.is_valid(self.registry))
        self.registry["schemaVersion"] = "1.0"
        self.registry["startupOrder"] = []
        self.assertFalse(self.validator.is_valid(self.registry))

    def test_unknown_values_cannot_be_promoted_to_runtime_config(self):
        self.registry["nodes"][0]["variants"]["real"]["execution"]["mainClass"] = None
        self.assertFalse(self.validator.is_valid(self.registry))

    def test_ports_must_be_real_integer_ports(self):
        for port in (0, 65536, True, "8080"):
            with self.subTest(port=port):
                self.registry["nodes"][0]["variants"]["real"]["endpoints"]["http"]["bind"]["port"] = port
                self.assertFalse(self.validator.is_valid(self.registry))

    def test_runner_specific_fields_are_required(self):
        execution = self.registry["nodes"][1]["variants"]["real"]["execution"]
        del execution["service"]
        self.assertFalse(self.validator.is_valid(self.registry))

    def test_system_properties_use_a_named_map(self):
        self.registry["defaults"]["vmOptions"].append("-Dpayment.url=http://localhost")
        self.assertFalse(self.validator.is_valid(self.registry))

    def test_secret_reference_is_named_not_an_unknown_placeholder(self):
        value = self.registry["nodes"][0]["variants"]["real"]["env"]["DB_PASSWORD"]
        self.assertEqual(value, {"fromEnv": "LOCAL_DB_PASSWORD"})
        value["fromEnv"] = ""
        self.assertFalse(self.validator.is_valid(self.registry))


if __name__ == "__main__":
    unittest.main()
