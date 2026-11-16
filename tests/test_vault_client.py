import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("vault_demo_client", ROOT / "examples/demo/vault_client.py")
CLIENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLIENT)
BODY = json.loads((ROOT / "examples/demo/docker/vault-mock/__files/injector-demo.json").read_text(encoding="utf-8"))


class VaultClientTest(unittest.TestCase):
    def test_reads_kv_v2_envelope_and_sends_token_header(self):
        with patch.object(CLIENT, "urlopen", return_value=io.BytesIO(json.dumps(BODY).encode())) as read:
            config = CLIENT.load_config("http://localhost:18083/", "/secret/data/injector-demo", "dummy")
        self.assertEqual(config, BODY["data"]["data"])
        request = read.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:18083/v1/secret/data/injector-demo")
        self.assertEqual({key.lower(): value for key, value in request.headers.items()}["x-vault-token"], "dummy")

    def test_config_values_control_behavior_without_printing_credentials(self):
        config = dict(BODY["data"]["data"])
        self.assertEqual(CLIENT.summarize(config)["message"], config["message"])
        config["feature_enabled"] = False
        result = CLIENT.summarize(config)
        self.assertEqual(result["message"], "feature disabled")
        self.assertTrue(result["databaseConfigured"])
        self.assertNotIn(config["database_password"], json.dumps(result))
        self.assertNotIn(config["database_username"], json.dumps(result))

    def test_missing_environment_is_reported_without_traceback(self):
        output = io.StringIO()
        with patch.dict("os.environ", {}, clear=True), contextlib.redirect_stderr(output):
            self.assertEqual(CLIENT.main(), 1)
        self.assertNotIn("Traceback", output.getvalue())

    def test_request_errors_do_not_print_response_or_token(self):
        environment = {"VAULT_ADDR": "http://localhost", "VAULT_PATH": "secret/data/demo", "VAULT_TOKEN": "hidden-token"}
        for error in (HTTPError("http://localhost", 403, "hidden-token", {}, None), URLError("hidden-token")):
            with self.subTest(error=type(error).__name__):
                output = io.StringIO()
                with patch.dict("os.environ", environment), patch.object(CLIENT, "load_config", side_effect=error), \
                        contextlib.redirect_stderr(output):
                    self.assertEqual(CLIENT.main(), 1)
                self.assertNotIn("hidden-token", output.getvalue())


if __name__ == "__main__":
    unittest.main()
