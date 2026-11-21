import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from injector_core.registration import inspect_draft, run_registration
from injector_core.registry import RegistryError
from injector_core.runtime import select_plan


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "launch.txt").write_text("orders\ncatalog\norders uses catalog\n", encoding="utf-8")
        self.draft = {"draftVersion": "0.1", "status": "draft",
                      "scope": {"profile": "local", "targets": ["orders"]},
                      "nodes": [], "dependencies": [], "nameMappings": [], "findings": [],
                      "startupOrder": ["catalog", "orders"], "evidence": []}
        for line, (name, port) in enumerate((("orders", 19081), ("catalog", 19082)), 1):
            self.draft["nodes"].append({"id": name, "kind": "application", "repoPath": ".",
                "execution": {"mode": "process", "command": ["node", name + ".js"], "workingDirectory": "."},
                "readiness": {"type": "http", "endpoint": "http", "path": "/", "timeoutSeconds": 10},
                "endpoints": [{"id": "http", "protocol": "http", "bind": {"host": "127.0.0.1", "port": port},
                    "addresses": [{"from": "host", "host": "127.0.0.1", "port": port, "scheme": "http"}]}]})
            self.evidence("/nodes/" + str(line - 1), line)
        self.draft["dependencies"].append({"from": "orders", "to": "catalog", "endpoint": "http",
            "injections": [{"channel": "environment", "key": "CATALOG_URL",
                            "source": {"node": "catalog", "endpoint": "http", "from": "host", "component": "url"}}]})
        self.evidence("/dependencies/0", 3)
        self.output = self.root / "candidate.json"

    def evidence(self, field, line):
        self.draft["evidence"].append({"field": field, "status": "observed",
                                       "locations": [{"path": "launch.txt", "line": line}]})

    def convert(self):
        path = self.root / "draft.json"
        path.write_text(json.dumps(self.draft), encoding="utf-8")
        return run_registration("draft-convert", path, self.root, self.output)

    def test_converts_verified_graph_and_preserves_existing_registry(self):
        self.assertFalse(inspect_draft(self.draft)["blockers"])
        self.assertEqual(self.convert()["order"], ["catalog", "orders"])
        original = self.output.read_bytes()
        data, plan = select_plan(self.root, "orders", "local", registry=self.output)
        self.assertEqual(plan["order"], ["catalog", "orders"])
        self.assertEqual(data["nodes"][0]["variants"]["local"]["injections"][0]["source"]["context"], "host")
        with self.assertRaisesRegex(RegistryError, "already exists"):
            self.convert()
        self.assertEqual(self.output.read_bytes(), original)

    def test_incomplete_draft_remains_reviewable_without_creating_registry(self):
        self.draft["nodes"][0]["execution"] = None
        self.draft["findings"] = [{"id": "Q-01", "severity": "blocking", "field": "/nodes/0/execution"}]
        self.assertEqual(inspect_draft(self.draft)["blockers"], ["Q-01"])
        with self.assertRaisesRegex(RegistryError, "Q-01"):
            self.convert()
        self.draft["findings"].clear()
        with self.assertRaisesRegex(RegistryError, "nodes/0/execution: unresolved"):
            self.convert()
        self.assertFalse(self.output.exists())

    def test_rejects_missing_evidence_cycle_and_host_collision(self):
        edge_evidence = self.draft["evidence"].pop()
        with self.assertRaisesRegex(RegistryError, "missing evidence"):
            self.convert()
        self.draft["evidence"].append(edge_evidence)
        self.draft["dependencies"].append({"from": "catalog", "to": "orders", "endpoint": None, "injections": []})
        self.evidence("/dependencies/1", 3)
        with self.assertRaisesRegex(RegistryError, "dependency cycle"):
            self.convert()
        self.draft["dependencies"].pop()
        self.draft["evidence"].pop()
        self.draft["nodes"][1]["endpoints"][0]["addresses"][0]["port"] = 19081
        with self.assertRaisesRegex(RegistryError, "host port conflicts"):
            self.convert()
        self.assertFalse(self.output.exists())

    def test_invalid_output_encoding_does_not_create_candidate(self):
        self.draft["nodes"][0]["execution"]["environment"] = {"LOCAL_NOTE": "\ud800"}
        with self.assertRaises(UnicodeEncodeError):
            self.convert()
        self.assertFalse(self.output.exists())
