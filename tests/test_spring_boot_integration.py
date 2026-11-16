"""Set INJECTOR_TEST_SPRING_JAR and INJECTOR_TEST_JAVA for the real Boot probe."""
import copy
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
from urllib.error import URLError
from urllib.request import urlopen

from injector_core.registry import load_registry
from injector_core.rendering import render_node

ROOT = Path(__file__).resolve().parents[1]
JAR = os.environ.get("INJECTOR_TEST_SPRING_JAR")
JAVA = os.environ.get("INJECTOR_TEST_JAVA")


@unittest.skipUnless(JAR and JAVA, "set the Spring probe jar and the real JDK java executable")
class SpringBootIntegrationTest(unittest.TestCase):
    def test_external_yaml_profile_and_vm_only_properties(self):
        data = copy.deepcopy(load_registry(ROOT / "examples/spring-config", "local"))
        with socket.socket() as address:
            address.bind(("127.0.0.1", 0))
            port = address.getsockname()[1]
        variant = data["nodes"][0]["variants"]["real"]
        variant["springProperties"]["server.port"] = port
        with tempfile.TemporaryDirectory(prefix="spring boot probe ") as directory:
            artifact = render_node(data, directory, "local", "spring-probe", environ={})
            self.assertIn("${PROBE_SECRET}", artifact.yaml_path.read_text(encoding="utf-8"))
            with (Path(directory) / "spring.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen([JAVA, *artifact.settings.jvm_arguments(), "-jar", str(Path(JAR).resolve())],
                                           cwd=directory, env={**os.environ, **artifact.settings.env,
                                                               "PROBE_SECRET": "integration-only-value"},
                                           stdout=log, stderr=subprocess.STDOUT)
                try:
                    deadline = time.monotonic() + 45
                    while True:
                        try:
                            with urlopen(f"http://127.0.0.1:{port}/probe", timeout=1) as response:
                                result = json.load(response)
                            break
                        except (URLError, TimeoutError):
                            if process.poll() is not None or time.monotonic() >= deadline:
                                self.fail("Spring Boot probe failed to become ready; inspect the build/runtime setup")
                            time.sleep(0.1)
                    self.assertEqual(result["message"], "value-from-generated-yaml")
                    self.assertEqual(result["vmOnly"], "value-from-vm-property")
                    self.assertEqual(result["labels"], ["local-a", "local-b"])
                    self.assertTrue(result["yamlIsNotSystemProperty"])
                    self.assertTrue(result["secretMatchesEnvironment"])
                    self.assertNotIn("integration-only-value", json.dumps(result))
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
