import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import injector


class ConfigurationTest(unittest.TestCase):
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
