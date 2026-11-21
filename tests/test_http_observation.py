import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from injector_core.observation import observe_http
from injector_core.registry import RegistryError, runtime_directory
from injector_core.runtime import prepare, stop
from test_runtime import free_port
from verifier.compare_observations import compare_observations


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo" / "http-observation"


def artifact(coverage="observed"):
    calls = [{"method": "POST", "path": "/lookup", "status": 200, "requestFields": {"/warehouse": "seoul"},
              "responseFields": {"/available": True}}] if coverage == "observed" else []
    return {"schemaVersion": 1, "scenario": "place-order", "scenarioDigest": "0" * 64,
            "profile": "local", "variants": {"orders": "local", "catalog": "local"},
            "edge": {"caller": "orders", "dependency": "catalog", "endpoint": "http"},
            "coverage": coverage, "calls": calls, "target": {"status": 201, "fields": {"/accepted": True}}}


class HTTPObservationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name).resolve()
        for name in ("service.py", "scenario.json"):
            shutil.copy2(DEMO / name, self.project / name)
        data = json.loads((DEMO / "registry.json").read_bytes())
        ports = set()
        for node in data["nodes"]:
            port = free_port()
            while port in ports:
                port = free_port()
            ports.add(port)
            variant = node["variants"]["local"]
            variant["execution"]["command"][0] = sys.executable
            variant["env"]["DEMO_PORT"] = str(port)
            endpoint = variant["endpoints"]["http"]
            endpoint["bind"]["port"] = endpoint["addresses"]["host"]["port"] = port
        (self.project / "registry.json").write_text(json.dumps(data), encoding="utf-8")

    def cli(self, *arguments, warehouse="seoul", skip=False):
        return subprocess.run([sys.executable, str(ROOT / "injector.py"), *map(str, arguments)],
                              cwd=ROOT, capture_output=True, text=True, timeout=30,
                              env={**os.environ, "INJECTOR_DEMO_WAREHOUSE": warehouse, "DEMO_SKIP_LOOKUP": str(int(skip))})

    def record(self, name, warehouse="seoul", skip=False):
        path = self.project / name
        result = self.cli("observe-http", "orders", "--project", self.project, "--profile", "local",
                          "--scenario", self.project / "scenario.json", "--output", path,
                          warehouse=warehouse, skip=skip)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((runtime_directory(self.project) / "session.json").exists())
        return path

    def test_same_target_response_can_hide_a_changed_dependency_request(self):
        baseline = self.record("before.json")
        candidate = self.record("after.json", "busan")
        absent = self.record("skip.json", skip=True)
        before = json.loads(baseline.read_bytes())
        after = json.loads(candidate.read_bytes())
        self.assertEqual(before["target"], after["target"])
        self.assertEqual(before["calls"][0]["requestFields"], {"/warehouse": "seoul"})
        self.assertNotIn(b"internalNote", baseline.read_bytes())
        self.assertEqual(self.cli("compare-http", baseline, "--candidate", baseline).returncode, 0)
        changed = self.cli("compare-http", baseline, "--candidate", candidate)
        self.assertEqual(changed.returncode, 1, changed.stderr)
        self.assertEqual(json.loads(changed.stdout)["changes"],
                         [{"path": "/calls/0/requestFields/~1warehouse", "kind": "changed"}])
        missing = self.cli("compare-http", baseline, "--candidate", absent)
        self.assertEqual(missing.returncode, 2, missing.stderr)
        self.assertEqual(json.loads(missing.stdout)["verdict"], "INCONCLUSIVE")

    def test_selected_query_values_are_compared_without_recording_other_parameters(self):
        fixture = self.project / "service.py"
        content = fixture.read_text(encoding="utf-8")
        content = content.replace('self.path == "/lookup"', 'self.path.split("?")[0] == "/lookup"')
        content = content.replace('os.environ["DEMO_WAREHOUSE"],', '"fixed",')
        content = content.replace('+ "lookup", data=body',
                                  '+ "lookup?tag=one&tag=&token=private&warehouse=" + os.environ["DEMO_WAREHOUSE"], data=body')
        fixture.write_text(content, encoding="utf-8")
        unconfigured = self.record("unconfigured.json")
        self.assertEqual(json.loads(unconfigured.read_bytes())["coverage"], "incomplete")
        self.assertEqual(self.cli("compare-http", unconfigured, "--candidate", unconfigured).returncode, 2)

        scenario = self.project / "scenario.json"
        configured = json.loads(scenario.read_bytes())
        configured["requestQuery"] = ["warehouse", "tag"]
        scenario.write_text(json.dumps(configured), encoding="utf-8")
        baseline = self.record("query-before.json")
        candidate = self.record("query-after.json", "busan")
        self.assertEqual(json.loads(baseline.read_bytes())["calls"][0]["requestQuery"],
                         {"warehouse": ["seoul"], "tag": ["one", ""]})
        self.assertNotIn(b"private", baseline.read_bytes())
        changed = self.cli("compare-http", baseline, "--candidate", candidate)
        self.assertEqual(changed.returncode, 1, changed.stderr)
        self.assertEqual(json.loads(changed.stdout)["changes"],
                         [{"path": "/calls/0/requestQuery/warehouse/0", "kind": "changed"}])

    def test_observation_never_replaces_an_active_session(self):
        with patch.dict(os.environ, {"INJECTOR_DEMO_WAREHOUSE": "seoul"}):
            prepare(self.project, "orders", "local")
            session = runtime_directory(self.project) / "session.json"
            original = session.read_bytes()
            try:
                output = self.project / "capture.json"
                with self.assertRaisesRegex(RegistryError, "stop the active"):
                    observe_http(self.project, "orders", "local", self.project / "scenario.json", output)
                self.assertEqual(session.read_bytes(), original)
                self.assertFalse(output.exists())
            finally:
                stop(self.project)

    def test_compares_checkouts_sequentially_using_the_same_registry_and_ports(self):
        with TemporaryDirectory() as folder:
            candidate = Path(folder) / "candidate checkout"
            shutil.copytree(self.project, candidate)
            registry = self.project / "registry.json"
            args = ("compare-worktrees", "orders", "--project", self.project, "--candidate-project", candidate,
                    "--registry", registry, "--profile", "local", "--scenario", self.project / "scenario.json")
            matching = self.cli(*args, "--output", self.project / "matching")
            self.assertEqual(matching.returncode, 0, matching.stderr)
            self.assertEqual(json.loads(matching.stdout)["verdict"], "PASS")

            service = candidate / "service.py"
            content = service.read_text(encoding="utf-8").replace('os.environ["DEMO_WAREHOUSE"]', '"busan"')
            service.write_text(content, encoding="utf-8")
            changed = self.cli(*args, "--output", self.project / "changed")
            self.assertEqual(changed.returncode, 1, changed.stderr)
            report = json.loads(changed.stdout)
            self.assertEqual(report["changes"], [{"path": "/calls/0/requestFields/~1warehouse", "kind": "changed"}])
            for side, checkout in (("baseline", self.project), ("candidate", candidate)):
                self.assertFalse((runtime_directory(checkout, registry) / "session.json").exists())
                self.assertEqual(Path(report["artifacts"][side]), self.project / "changed" / f"{side}.json")
            before = json.loads(Path(report["artifacts"]["baseline"]).read_bytes())
            after = json.loads(Path(report["artifacts"]["candidate"]).read_bytes())
            self.assertEqual(before["scenarioDigest"], after["scenarioDigest"])
            self.assertEqual(before["target"], after["target"])

    def test_worktree_comparison_protects_existing_output_and_candidate_session(self):
        with TemporaryDirectory() as folder:
            candidate = Path(folder) / "candidate"
            shutil.copytree(self.project, candidate)
            args = ("compare-worktrees", "orders", "--project", self.project, "--candidate-project", candidate,
                    "--profile", "local", "--scenario", self.project / "scenario.json")
            output = self.project / "capture"
            output.mkdir()
            sentinel = output / "baseline.json"
            sentinel.write_bytes(b"existing")
            existing = self.cli(*args, "--output", output)
            self.assertEqual(existing.returncode, 2)
            self.assertIn("output directory already exists", existing.stderr)
            self.assertEqual(sentinel.read_bytes(), b"existing")

            with patch.dict(os.environ, {"INJECTOR_DEMO_WAREHOUSE": "seoul"}):
                prepare(candidate, "orders", "local")
            session = runtime_directory(candidate) / "session.json"
            try:
                original = session.read_bytes()
                blocked = self.cli(*args, "--output", self.project / "blocked")
                self.assertEqual(blocked.returncode, 2)
                self.assertIn("candidate: stop the active Injector session", blocked.stderr)
                self.assertFalse((self.project / "blocked").exists())
                self.assertFalse(runtime_directory(self.project).exists())
                self.assertEqual(session.read_bytes(), original)
            finally:
                stop(candidate)

    def test_unrecorded_fields_and_incompatible_plans_have_distinct_results(self):
        candidate = artifact()
        candidate["calls"][0]["requestFields"]["/optional"] = None
        self.assertEqual(compare_observations(artifact(), candidate)["changes"],
                         [{"path": "/calls/0/requestFields/~1optional", "kind": "added"}])
        candidate["variants"]["catalog"] = "mock"
        self.assertEqual(compare_observations(artifact(), candidate)["verdict"], "INCONCLUSIVE")
