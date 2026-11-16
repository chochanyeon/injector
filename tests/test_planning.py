import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import injector
from injector_core.planning import build_plan
from injector_core.registry import RegistryError
from injector_core.resolution import resolve_node

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((ROOT / "examples/registry/registry.json").read_text(encoding="utf-8"))


def graph(edges, targets):
    nodes = []
    for name, dependencies in edges.items():
        variant = copy.deepcopy(EXAMPLE["nodes"][2]["variants"]["real"])
        variant["dependencies"] = dependencies
        nodes.append({"id": name, "kind": "application", "variants": {"real": variant}})
    return {"schemaVersion": "1.0", "nodes": nodes,
            "profiles": {"local": {"targets": targets, "selections": {name: "real" for name in edges}}}}


class PlanningTest(unittest.TestCase):
    def test_shared_dependency_precedes_both_consumers_once(self):
        data = graph({"a": ["b", "c"], "b": ["d"], "c": ["d", "e"], "d": [], "e": []}, ["a"])
        self.assertEqual(build_plan(data, "local")["order"], ["d", "b", "e", "c", "a"])

    def test_real_and_mock_choose_different_transitive_edges(self):
        self.assertEqual(build_plan(EXAMPLE, "local-real")["order"], ["database", "catalog", "orders"])
        plan = build_plan(EXAMPLE, "local-mock")
        self.assertEqual(plan["order"], ["catalog", "database", "orders"])
        catalog = plan["steps"][0]
        self.assertEqual(catalog["variant"], "mock")
        self.assertEqual(catalog["dependencies"], [])

    def test_mock_removes_database_if_no_other_consumer_requires_it(self):
        data = copy.deepcopy(EXAMPLE)
        variant = data["nodes"][0]["variants"]["real"]
        variant["dependencies"] = ["catalog"]
        variant["injections"] = variant["injections"][:1]
        self.assertEqual(build_plan(data, "local-mock")["order"], ["catalog", "orders"])

    def test_unreachable_cycles_are_not_traversed(self):
        data = graph({"a": ["b"], "b": [], "unused": ["unused"]}, ["a"])
        self.assertEqual(build_plan(data, "local")["order"], ["b", "a"])

    def test_multiple_targets_preserve_declaration_order_and_share_resources(self):
        data = graph({"a": ["c"], "b": ["c"], "c": []}, ["b", "a"])
        self.assertEqual(build_plan(data, "local")["order"], ["c", "b", "a"])

    def test_cycles_include_actual_path(self):
        for edges, targets, path in (({"a": ["a"]}, ["a"], "a -> a"),
                                     ({"a": ["b"], "b": ["c"], "c": ["a"]}, ["a"], "a -> b -> c -> a")):
            with self.subTest(path=path), self.assertRaisesRegex(RegistryError, path):
                build_plan(graph(edges, targets), "local")

    def test_long_chains_do_not_use_python_recursion_depth(self):
        edges = {f"n{i}": [f"n{i + 1}"] if i < 1499 else [] for i in range(1500)}
        plan = build_plan(graph(edges, ["n0"]), "local")
        self.assertEqual(plan["order"], [f"n{i}" for i in reversed(range(1500))])

    def test_missing_selection_or_dependency_cannot_be_planned(self):
        data = graph({"a": ["b"], "b": []}, ["a"])
        del data["profiles"]["local"]["selections"]["b"]
        with self.assertRaisesRegex(RegistryError, "selection for b"):
            build_plan(data, "local")
        data["nodes"][0]["variants"]["real"]["dependencies"] = ["missing"]
        with self.assertRaisesRegex(RegistryError, "selection for missing"):
            build_plan(data, "local")

    def test_graph_plan_then_settings_preflight_can_run_before_any_launch(self):
        data = copy.deepcopy(EXAMPLE)
        plan = build_plan(data, "local-real")
        settings = {name: resolve_node(data, "local-real", name, {"LOCAL_DB_PASSWORD": "fixture"})
                    for name in plan["order"]}
        self.assertEqual(settings["orders"].env["CATALOG_URL"], "http://catalog.local.test.com:18082/")
        self.assertEqual(settings["catalog"].env["DB_HOST"], "database")

    def test_cli_plan_is_side_effect_free_and_does_not_need_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text(json.dumps(EXAMPLE), encoding="utf-8")
            original = path.read_bytes()
            output = io.StringIO()
            with patch("sys.argv", ["injector.py", "plan", "--project", directory, "--profile", "local-real"]), \
                    patch.dict("os.environ", {}, clear=True), patch("subprocess.run") as execute, \
                    patch.object(injector, "generate") as generate, contextlib.redirect_stdout(output):
                injector.main()
            execute.assert_not_called()
            generate.assert_not_called()
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [path])
            plan = json.loads(output.getvalue())
            self.assertEqual(plan["order"], ["database", "catalog", "orders"])
            self.assertNotIn("DB_PASSWORD", output.getvalue())


if __name__ == "__main__":
    unittest.main()
