"""Demo app consuming the supported KV v2 API; not a general Vault SDK."""
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def load_config(address, path, token):
    request = Request(address.rstrip("/") + "/v1/" + path.lstrip("/"),
                      headers={"X-Vault-Token": token, "Accept": "application/json"})
    with urlopen(request, timeout=5) as response:
        return json.load(response)["data"]["data"]


def summarize(config):
    return {"message": config["message"] if config["feature_enabled"] else "feature disabled",
            "databaseConfigured": bool(config["database_username"] and config["database_password"])}


def main():
    try:
        config = load_config(os.environ["VAULT_ADDR"], os.environ["VAULT_PATH"], os.environ["VAULT_TOKEN"])
        print(json.dumps(summarize(config), ensure_ascii=False))
    except HTTPError as error:
        print(f"Vault mock request failed (HTTP {error.code})", file=sys.stderr)
        return 1
    except URLError:
        print("Vault mock is unreachable", file=sys.stderr)
        return 1
    except (KeyError, ValueError, TypeError):
        print("Vault demo requires its configured environment and KV v2 data fields", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
