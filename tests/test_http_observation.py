import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from injector_core.observation import observe_http
from injector_core.registry import RegistryError, runtime_directory
from injector_core.runtime import _lock, prepare, stop
from test_runtime import free_port
from verifier.compare_observations import compare_observations
from verifier.worktree_suite import verify_suite


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
            report = json.loads(matching.stdout)
            self.assertEqual(report["verdict"], "PASS")
            self.assertEqual(json.loads(Path(report["report"]).read_bytes()), report)
            self.assertIn({"node": "orders", "phase": "ready"}, report["runs"]["candidate"]["events"])

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

            service.write_text("raise SystemExit(3)\n", encoding="utf-8")
            failed = self.cli(*args, "--output", self.project / "startup-failed")
            self.assertEqual(failed.returncode, 2, failed.stderr)
            report = json.loads(failed.stdout)
            self.assertEqual(json.loads(Path(report["report"]).read_bytes()), report)
            self.assertEqual(report["verdict"], "INCONCLUSIVE")
            self.assertEqual(set(report["artifacts"]), {"baseline"})
            self.assertEqual(report["runs"]["candidate"]["status"], "failed")
            self.assertIn("exited before readiness", report["runs"]["candidate"]["reason"])
            self.assertFalse((runtime_directory(candidate, registry) / "session.json").exists())

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

    def suite(self, *, second_case=None):
        first = json.loads((DEMO / "scenario.json").read_bytes())
        first["targetFields"].append("/requests")
        (self.project / "scenario.json").write_text(json.dumps(first), encoding="utf-8")
        second = {**first, "name": "order-regression", "request": {**first["request"], "json": {"product": "extra"}}}
        (self.project / "second scenario.json").write_text(json.dumps(second), encoding="utf-8")
        suite = self.project / "suite.json"
        suite.write_text(json.dumps({"schemaVersion": 1, "name": "orders-suite", "target": "orders", "profile": "local",
                                     "cases": [{"scenario": "scenario.json"},
                                               second_case or {"scenario": "second scenario.json"}]}), encoding="utf-8")
        return suite

    def test_suite_continues_after_behavior_difference_and_starts_clean(self):
        suite = self.suite()
        service = self.project / "service.py"
        source = service.read_text(encoding="utf-8").replace("def reply(self, status, value):",
            "requests = 0\n\n    def reply(self, status, value):").replace('self.reply(201, {"accepted": True})',
            'type(self).requests += 1\n            self.reply(201, {"accepted": True, "requests": self.requests})')
        service.write_text(source, encoding="utf-8")
        with TemporaryDirectory() as folder:
            candidate = Path(folder) / "candidate"
            shutil.copytree(self.project, candidate)
            (candidate / "service.py").write_text(source.replace('os.environ["DEMO_WAREHOUSE"]',
                '"busan" if value["product"] == "sample" else os.environ["DEMO_WAREHOUSE"]'), encoding="utf-8")
            output = self.project / "evidence"
            result = self.cli("verify-suite", suite, "--project", self.project, "--candidate-project", candidate,
                              "--output", output)
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(json.loads((output / "report.json").read_bytes()), report)
            summary = (output / "summary.md").read_text(encoding="utf-8")
            self.assertIn("[Case report](02/report.json)", summary)
            self.assertIn("[Baseline](02/baseline.json)", summary)
            self.assertEqual(report["verdict"], "FAIL")
            self.assertEqual(report["counts"], {"PASS": 1, "FAIL": 1, "INCONCLUSIVE": 0, "NOT_RUN": 0})
            for verdict, entry in zip(("FAIL", "PASS"), report["cases"]):
                case_report = json.loads((output / entry["report"]).read_bytes())
                self.assertEqual(case_report["verdict"], verdict)
                for side in ("baseline", "candidate"):
                    self.assertEqual(case_report[side]["target"]["fields"]["/requests"], 1)
            for checkout in (self.project, candidate):
                self.assertFalse((runtime_directory(checkout) / "session.json").exists())

    def test_suite_preflights_later_cases_and_reports_remaining_cases_after_abort(self):
        invalid = self.suite(second_case={"scenario": "second scenario.json", "proveFix": "unknown"})
        with TemporaryDirectory() as folder, patch.dict(os.environ, {"INJECTOR_DEMO_WAREHOUSE": "seoul"}):
            candidate = Path(folder) / "candidate"
            shutil.copytree(self.project, candidate)
            output = self.project / "suite-output"
            with self.assertRaisesRegex(RegistryError, "suite case 2: the fix check"):
                verify_suite(invalid, self.project, candidate, output)
            arguments = (invalid, "--project", self.project, "--candidate-project", candidate)
            preflight = self.cli("check-suite", *arguments)
            attempt = self.cli("verify-suite", *arguments, "--output", output)
            self.assertEqual((preflight.returncode, attempt.returncode), (2, 2))
            diagnostics = json.loads(preflight.stdout)
            self.assertEqual(json.loads(attempt.stdout), diagnostics)
            self.assertEqual(diagnostics["diagnostics"][0]["code"], "invalid_fix_check")
            self.assertEqual(diagnostics["diagnostics"][0]["case"], 2)
            self.assertFalse(output.exists())
            self.assertFalse(runtime_directory(self.project).exists())
            suite = self.suite()
            with patch("injector_core.observation._record_http", side_effect=RegistryError("runner could not start")):
                report = verify_suite(suite, self.project, candidate, output)
            self.assertEqual(report["verdict"], "INCONCLUSIVE")
            self.assertEqual([case["verdict"] for case in report["cases"]], ["INCONCLUSIVE", "NOT_RUN"])
            with patch("injector_core.observation._record_http", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    verify_suite(suite, self.project, candidate, self.project / "interrupted")
            interrupted_root = self.project / "interrupted"
            summary = json.loads((interrupted_root / "report.json").read_bytes())
            run = json.loads((interrupted_root / summary["cases"][0]["report"]).read_bytes())
            self.assertEqual(run["runs"]["baseline"]["status"], "interrupted")
            self.assertEqual(summary["cases"][1]["verdict"], "NOT_RUN")

    def test_suite_check_reports_worktree_blockers_without_writing_runtime_files(self):
        suite = self.suite()
        runtime = runtime_directory(self.project)
        runtime.mkdir(parents=True)
        with TemporaryDirectory() as folder:
            candidate = Path(folder) / "candidate"
            shutil.copytree(self.project, candidate)
            arguments = (suite, "--project", self.project, "--candidate-project", candidate)
            ready = self.cli("check-suite", *arguments, warehouse="value-must-not-appear")
            self.assertEqual(ready.returncode, 0, ready.stderr)
            self.assertNotIn("value-must-not-appear", ready.stdout)
            payload = json.loads(ready.stdout)
            self.assertEqual(payload["status"], "READY")
            self.assertEqual(payload["worktrees"]["candidate"]["order"], ["catalog", "orders"])

            candidate_file = candidate / "registry.json"
            registry = json.loads(candidate_file.read_bytes())
            orders = registry["nodes"][0]["variants"]["local"]
            orders["env"]["DEMO_WAREHOUSE"] = {"fromEnv": "INJECTOR_SUITE_TEST_UNSET"}
            candidate_file.write_text(json.dumps(registry), encoding="utf-8")
            address = registry["nodes"][1]["variants"]["local"]["endpoints"]["http"]["addresses"]["host"]
            with socket.socket() as listener:
                listener.bind((address["host"], address["port"]))
                listener.listen()
                blocked = self.cli("check-suite", *arguments)
            self.assertEqual(blocked.returncode, 2, blocked.stderr)
            payload = json.loads(blocked.stdout)
            self.assertEqual(payload["status"], "BLOCKED")
            port, missing = payload["diagnostics"]
            self.assertEqual((port["side"], port["node"], port["port"], port["code"]),
                             ("baseline", "catalog", address["port"], "port_in_use"))
            self.assertEqual((missing["side"], missing["node"], missing["variable"], missing["code"]),
                             ("candidate", "orders", "INJECTOR_SUITE_TEST_UNSET", "missing_environment"))
            self.assertFalse(list(runtime.iterdir()))
            self.assertFalse(list(runtime_directory(candidate).iterdir()))
            with _lock(runtime):
                locked = self.cli("check-suite", *arguments)
                self.assertEqual(locked.returncode, 2, locked.stderr)
                diagnostics = json.loads(locked.stdout)["diagnostics"]
                self.assertEqual((diagnostics[0]["side"], diagnostics[0]["code"]), ("baseline", "session_blocked"))
