import json
from pathlib import Path
import shutil
import socket
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.request import ProxyHandler, build_opener

from injector_core.registration import run_registration
from injector_core.registry import RegistryError, runtime_directory
from injector_core.runtime import prepare, select_plan, stop
from test_runtime import free_port


SERVICE = Path(__file__).resolve().parents[1] / "examples" / "demo" / "multi-app" / "service.py"


def reviewed_draft(project, profile):
    ports = set()
    nodes = []
    for role in ("db", "catalog", "orders"):
        port = free_port()
        while port in ports:
            port = free_port()
        ports.add(port)
        runner = {"real": "catalog", "mock": "mock", "fail": "fail"}[profile] if role == "catalog" else role
        nodes.append({"id": role, "kind": "infrastructure" if role == "db" else "application",
            "repoPath": ".", "execution": {"mode": "process", "workingDirectory": ".",
                "command": [sys.executable, "service.py", runner],
                "environment": {"DEMO_PORT": str(port), "DEMO_DATABASE": str(project / "shared.db")}},
            "endpoints": [{"id": "http", "protocol": "http", "bind": {"host": "127.0.0.1", "port": port},
                "addresses": [{"from": "host", "host": "127.0.0.1", "port": port, "scheme": "http"}]}],
            "readiness": {"type": "http", "endpoint": "http", "path": "/health", "timeoutSeconds": 5}})
    dependencies = [{"from": "orders", "to": "catalog", "endpoint": "http", "injections": [
            {"channel": "environment", "key": "CATALOG_URL",
             "source": {"node": "catalog", "endpoint": "http", "from": "host", "component": "url"}}]},
        {"from": "orders", "to": "db", "endpoint": None, "injections": []}]
    if profile != "mock":
        dependencies.append({"from": "catalog", "to": "db", "endpoint": None, "injections": []})
    order = ["catalog", "db", "orders"] if profile == "mock" else ["db", "catalog", "orders"]
    evidence = [{"field": f"/{section}/{index}", "status": "proposed", "locations": []}
                for section, values in (("nodes", nodes), ("dependencies", dependencies))
                for index in range(len(values))]
    evidence.append({"field": "/dependencies/0/injections/0", "status": "observed",
                     "locations": [{"path": "service.py", "line": 31}]})
    return {"draftVersion": "0.1", "status": "draft", "scope": {"profile": profile, "targets": ["orders"]},
            "nodes": nodes, "dependencies": dependencies, "nameMappings": [], "evidence": evidence,
            "findings": [], "startupOrder": order}


class MultiAppIntegration(unittest.TestCase):
    def test_registration_execution_switching_and_cleanup(self):
        with TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            settings = root / "registry library"
            settings.mkdir()
            for profile in ("real", "mock", "fail"):
                with self.subTest(profile=profile):
                    worktree = root / ("alternate checkout" if profile == "mock" else "main checkout")
                    worktree.mkdir(exist_ok=True)
                    shutil.copy2(SERVICE, worktree / "service.py")
                    data = reviewed_draft(worktree, profile)
                    draft = settings / f"{profile}-draft.json"
                    draft.write_text(json.dumps(data), encoding="utf-8")
                    registry = settings / f"{profile}.json"
                    converted = run_registration("draft-convert", draft, worktree, registry)
                    self.assertEqual(converted["order"], data["startupOrder"])
                    events = []
                    try:
                        if profile == "fail":
                            with self.assertRaisesRegex(RegistryError, "exited before readiness"):
                                prepare(worktree, "orders", profile, registry=registry, emit=events.append)
                            self.assertEqual([item["node"] for item in events if item["phase"] == "ready"], ["db"])
                            self.assertIn({"node": "db", "phase": "stopping"}, events)
                        else:
                            result = prepare(worktree, "orders", profile, registry=registry, emit=events.append)
                            self.assertEqual(result["order"], data["startupOrder"])
                            endpoint = data["nodes"][-1]["endpoints"][0]["bind"]
                            opener = build_opener(ProxyHandler({}))
                            with opener.open(f"http://127.0.0.1:{endpoint['port']}/order", timeout=5) as response:
                                order = json.load(response)
                            self.assertEqual(order["product"]["source"], profile)
                            expected = {"catalog": 1, "orders": 1} if profile == "real" else {"orders": 1}
                            self.assertEqual(order["counts"], expected)
                    finally:
                        stop(worktree, registry=registry)
                    self.assertFalse((runtime_directory(worktree, registry) / "session.json").exists())
                    self.assertTrue((worktree / "shared.db").is_file())
                    for node in data["nodes"]:
                        port = node["endpoints"][0]["bind"]["port"]
                        with self.assertRaises(OSError), socket.create_connection(("127.0.0.1", port), timeout=0.5):
                            self.fail("managed listener survived cleanup")

    def test_custom_hostname_blocks_prepare_when_resolved_elsewhere(self):
        with TemporaryDirectory() as temp:
            project = Path(temp).resolve()
            shutil.copy2(SERVICE, project / "service.py")
            data = reviewed_draft(project, "mock")
            alias = "catalog.injector.test"
            data["nodes"][1]["endpoints"][0]["addresses"][0]["host"] = alias
            data["nameMappings"] = [{"hostname": alias, "address": "127.0.0.1", "mechanism": "external"}]
            draft, registry = project / "draft.json", project / "runtime.json"
            draft.write_text(json.dumps(data), encoding="utf-8")
            run_registration("draft-convert", draft, project, registry)
            self.assertEqual(select_plan(project, "orders", "mock", registry=registry)[1]["order"],
                             ["catalog", "db", "orders"])
            with patch("injector_core.hostnames.socket.getaddrinfo", return_value=[
                    (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.0.2.1", 0))]):
                with self.assertRaisesRegex(RegistryError, "expected to resolve only to"):
                    prepare(project, "orders", "mock", registry=registry)
            self.assertFalse((runtime_directory(project, registry) / "session.json").exists())
