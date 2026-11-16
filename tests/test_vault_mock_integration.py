"""Opt in with INJECTOR_TEST_VAULT_URL after starting the demo mock."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("INJECTOR_TEST_VAULT_URL")
TOKEN = "local-demo-token"
PATH = "/v1/secret/data/injector-demo"


@unittest.skipUnless(BASE, "set INJECTOR_TEST_VAULT_URL to run against the local WireMock")
class VaultMockIntegrationTest(unittest.TestCase):
    def request(self, path=PATH, token=TOKEN, method="GET"):
        headers = {} if token is None else {"X-Vault-Token": token}
        request = Request(BASE.rstrip("/") + path, headers=headers, method=method)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_known_path_returns_configured_kv_v2_data(self):
        status, body = self.request()
        expected = json.loads((ROOT / "examples/demo/docker/vault-mock/__files/injector-demo.json").read_text(encoding="utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(body["data"], expected["data"])

    def test_missing_and_incorrect_tokens_return_json_403(self):
        for token in (None, "incorrect"):
            with self.subTest(token=token):
                status, body = self.request(token=token)
                self.assertEqual(status, 403)
                self.assertEqual(body["errors"], ["permission denied"])

    def test_unknown_and_unsupported_requests_return_json_404(self):
        for path, method in (("/v1/secret/data/missing", "GET"), (PATH + "?version=999", "GET"), (PATH, "POST")):
            with self.subTest(path=path, method=method):
                status, body = self.request(path=path, method=method)
                self.assertEqual(status, 404)
                self.assertIn("errors", body)

    def test_demo_app_consumes_api_response(self):
        result = subprocess.run([sys.executable, str(ROOT / "examples/demo/vault_client.py")],
                                env={**os.environ, "VAULT_ADDR": BASE, "VAULT_TOKEN": TOKEN,
                                     "VAULT_PATH": "secret/data/injector-demo"},
                                capture_output=True, text=True, timeout=15, check=True)
        summary = json.loads(result.stdout)
        self.assertTrue(summary["databaseConfigured"])
        self.assertEqual(summary["message"], "Configuration loaded from local Vault API mock")
        self.assertNotIn("local-demo-only", result.stdout)


if __name__ == "__main__":
    unittest.main()
