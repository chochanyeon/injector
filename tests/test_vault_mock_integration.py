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
PATH = "/v1/secret/data/orders"


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
        for service in ("orders", "payments"):
            with self.subTest(service=service):
                status, body = self.request(path=f"/v1/secret/data/{service}")
                expected = json.loads((ROOT / f"examples/demo/docker/vault-mock/__files/{service}.json").read_text(encoding="utf-8"))
                self.assertEqual(status, 200)
                self.assertEqual(body["data"], expected["data"])

    def test_same_keys_have_service_specific_values(self):
        _, orders = self.request(path="/v1/secret/data/orders")
        _, payments = self.request(path="/v1/secret/data/payments")
        orders, payments = orders["data"]["data"], payments["data"]["data"]
        self.assertEqual(orders.keys(), payments.keys())
        self.assertNotEqual(orders["database_password"], payments["database_password"])
        self.assertNotEqual(orders["message"], payments["message"])

    def test_missing_and_incorrect_tokens_return_json_403(self):
        for token in (None, "incorrect"):
            with self.subTest(token=token):
                status, body = self.request(token=token)
                self.assertEqual(status, 403)
                self.assertEqual(body["errors"], ["permission denied"])

    def test_unknown_and_unsupported_requests_return_json_404(self):
        for path, method in (("/v1/secret/data/missing", "GET"), ("/v1/secret/data/injector-demo", "GET"),
                             (PATH + "?version=999", "GET"), (PATH, "POST")):
            with self.subTest(path=path, method=method):
                status, body = self.request(path=path, method=method)
                self.assertEqual(status, 404)
                self.assertIn("errors", body)

    def test_demo_app_consumes_api_response(self):
        for service in ("orders", "payments"):
            with self.subTest(service=service):
                result = subprocess.run([sys.executable, str(ROOT / "examples/demo/vault_client.py")],
                                        env={**os.environ, "VAULT_ADDR": BASE, "VAULT_TOKEN": TOKEN,
                                             "VAULT_PATH": f"secret/data/{service}"},
                                        capture_output=True, text=True, timeout=15, check=True)
                summary = json.loads(result.stdout)
                self.assertTrue(summary["databaseConfigured"])
                self.assertEqual(summary["message"], f"{service.title()} local configuration")
                self.assertNotIn(f"{service}-local-only", result.stdout)


if __name__ == "__main__":
    unittest.main()
