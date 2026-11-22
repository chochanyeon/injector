import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

import yaml

from injector_core.observation import compare_worktrees, observe_http
from injector_core.registry import runtime_directory
from injector_core.runtime import _docker, prepare, select_plan, stop
from test_runtime import free_port
from verifier.compare_observations import compare_files


DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo" / "monorepo"
SERVICES = {"storefront", "orders", "catalog", "pricing", "inventory", "notifications"}


class ShopPlanTests(unittest.TestCase):
    def test_profiles_preserve_shared_dependencies_and_switch_pricing(self):
        tail = ["catalog", "postgres", "inventory", "kafka", "orders", "notifications", "storefront"]
        for profile, prefix in (("real", ["pricing-db", "loki", "vault-mock", "pricing", "redis"]),
                                ("mock", ["vault-mock", "pricing", "redis", "loki"])):
            with self.subTest(profile=profile):
                _, plan = select_plan(DEMO, "storefront", profile)
                self.assertEqual(plan["order"], [*prefix, *tail])
                steps = {step["node"]: step for step in plan["steps"]}
                for service in sorted(SERVICES):
                    self.assertIn("vault-mock", steps[service]["dependencies"], service)
                self.assertEqual(steps["orders"]["dependencies"],
                                 ["catalog", "inventory", "postgres", "kafka", "loki", "vault-mock"])
                self.assertEqual(steps["notifications"]["dependencies"], ["kafka", "redis", "loki", "vault-mock"])
                self.assertEqual(steps["pricing"]["runner"], "process" if profile == "real" else "compose")


def copy_with_isolated_ports(project, compose_name):
    shutil.copytree(DEMO, project, ignore=shutil.ignore_patterns(".gradle", ".local", ".idea"))
    ports = {}

    def allocate(original):
        if original not in ports:
            port = free_port()
            while port in ports.values():
                port = free_port()
            ports[original] = port
        return ports[original]

    path = project / "infra" / "compose.yaml"
    compose = yaml.safe_load(path.read_bytes())
    for service in compose["services"].values():
        host, published, internal = service["ports"][0].split(":")
        service["ports"] = [f"{host}:{allocate(int(published))}:{internal}"]
    kafka = compose["services"]["kafka"]["environment"]
    kafka["KAFKA_ADVERTISED_LISTENERS"] = f"INTERNAL://kafka:9092,EXTERNAL://127.0.0.1:{ports[19762]}"
    path.write_text(yaml.safe_dump(compose), encoding="utf-8")
    for path in (project / "registry" / "nodes").glob("*.json"):
        node = json.loads(path.read_bytes())
        for variant in node["variants"].values():
            for endpoint in variant["endpoints"].values():
                address = endpoint["addresses"]["host"]
                address["port"] = allocate(address["port"])
                if variant["execution"]["type"] == "process":
                    endpoint["bind"]["port"] = address["port"]
                    variant["env"]["APP_PORT"] = str(address["port"])
            if variant["execution"]["type"] == "compose":
                variant["execution"]["projectName"] = compose_name
            elif os.environ.get("INJECTOR_TEST_JAVA"):
                variant["execution"]["command"][0] = os.environ["INJECTOR_TEST_JAVA"]
        path.write_text(json.dumps(node), encoding="utf-8")
    return ports


@unittest.skipUnless(os.environ.get("INJECTOR_TEST_SHOP"), "build the shop with installDist and opt in")
class ShopIntegrationTests(unittest.TestCase):
    def test_checkout_trace_detects_changed_topic_and_missing_consumer(self):
        name = "injector-shop-trace-" + uuid4().hex[:10]
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            baseline, candidate = root / "baseline shop", root / "candidate shop"
            copy_with_isolated_ports(baseline, name)
            shutil.copytree(baseline, candidate)
            scenario = baseline / "scenarios" / "checkout-trace.json"

            def set_topic(service, topic):
                fixture = candidate / "infra" / "vault" / "mappings" / f"{service}.json"
                mapping = json.loads(fixture.read_bytes())
                mapping["response"]["jsonBody"]["data"]["data"]["orderTopic"] = topic
                fixture.write_text(json.dumps(mapping), encoding="utf-8")

            try:
                for service in ("orders", "notifications"):
                    set_topic(service, "shop.orders.candidate")
                report = compare_worktrees(baseline, candidate, "storefront", "mock", scenario, root / "paired")
                self.assertEqual(report["verdict"], "FAIL", report)
                before, after = report["baseline"], report["candidate"]
                self.assertEqual(before["target"], after["target"])
                self.assertEqual(before["target"]["status"], 201)
                self.assertEqual(before["events"], [
                    {**event, "topic": "shop.orders"} if "topic" in event else event for event in after["events"]
                ])
                self.assertEqual(len(report["changes"]), 2)
                self.assertTrue(all(change["path"].endswith("/topic") for change in report["changes"]))
                edges = {(event["service"], event["dependency"]) for event in after["events"]
                         if event["event"] == "http_dependency"}
                self.assertEqual(edges, {("storefront", "orders"), ("orders", "catalog"),
                                         ("orders", "inventory"), ("catalog", "pricing")})
                baseline_path = Path(report["artifacts"]["baseline"])
                self.assertFalse((runtime_directory(baseline) / "session.json").exists())
                self.assertFalse((runtime_directory(candidate) / "session.json").exists())

                set_topic("notifications", "shop.orders.other")
                missing_path = root / "missing.json"
                captured = observe_http(candidate, "storefront", "mock", scenario, missing_path)
                self.assertEqual(captured["coverage"], "incomplete")
                missing = compare_files(baseline_path, missing_path)
                self.assertEqual(missing["verdict"], "INCONCLUSIVE")
                self.assertEqual(missing["candidate"]["missingEvents"],
                                 [{"service": "notifications", "event": "kafka_consume"}])
                self.assertEqual(missing["candidate"]["target"], before["target"])
                self.assertFalse((runtime_directory(candidate) / "session.json").exists())
            finally:
                stop(candidate)
                stop(baseline)
                label = f"label=com.docker.compose.project={name}"
                networks = _docker(["network", "ls", "-q", "--filter", label]).split()
                if networks:
                    _docker(["network", "rm", *networks])
                self.assertFalse(_docker(["ps", "-aq", "--filter", label]))

    def test_checkout_profiles_and_http_observation(self):
        self.assertTrue((DEMO / "services" / "storefront" / "build" / "install" / "storefront" / "lib").is_dir(),
                        "run the shop installDist task first")
        name = "injector-shop-test-" + uuid4().hex[:10]
        with TemporaryDirectory() as temporary:
            project = Path(temporary).resolve() / "shop checkout"
            ports = copy_with_isolated_ports(project, name)
            mock_price = 1149
            counter_key = "shop:test-checkout-count"
            for app, setting, value in (("pricing", "mockUnitCents", mock_price),
                                        ("storefront", "checkoutCounterKey", counter_key)):
                fixture_path = project / "infra" / "vault" / "mappings" / f"{app}.json"
                fixture = json.loads(fixture_path.read_bytes())
                fixture["response"]["jsonBody"]["data"]["data"][setting] = value
                fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
            opener = build_opener(ProxyHandler({}))

            def request(port, route, data=None, headers=None):
                body = json.dumps(data).encode("utf-8") if data is not None else None
                uri = f"http://127.0.0.1:{ports[port]}{route}"
                headers = {"Content-Type": "application/json", **(headers or {})}
                with opener.open(Request(uri, data=body, headers=headers), timeout=15) as response:
                    if "X-Request-Id" in headers:
                        self.assertEqual(response.headers.get("X-Request-Id"), headers["X-Request-Id"])
                    return response.status, json.load(response)

            try:
                for profile, source, price in (("real", "postgres", 1299), ("mock", "wiremock", mock_price)):
                    with self.subTest(profile=profile):
                        result = prepare(project, "storefront", profile)
                        self.assertEqual("pricing-db" in result["order"], profile == "real")
                        _, journal = request(19765, "/__admin/requests")
                        self.assertEqual({entry["request"]["url"] for entry in journal["requests"]
                                          if entry["request"]["url"].startswith("/v1/secret/data/")},
                                         {f"/v1/secret/data/{service}" for service in SERVICES})
                        token = {"X-Vault-Token": "shop-local-demo-token"}
                        for app, ttl in (("catalog", 75), ("notifications", 300)):
                            _, settings = request(19765, f"/v1/secret/data/{app}", headers=token)
                            self.assertEqual(settings["data"]["data"]["cacheTtlSeconds"], ttl)
                        for path, headers, code in (("catalog", None, 403), ("unknown", token, 404)):
                            with self.assertRaises(HTTPError) as denied:
                                request(19765, f"/v1/secret/data/{path}", headers=headers)
                            denied.exception.close()
                            self.assertEqual(denied.exception.code, code)
                        quote = request(19780, "/items/sample")[1]
                        self.assertEqual((quote["source"], quote["unitCents"], quote["cache"]), (source, price, "miss"))
                        self.assertEqual(request(19780, "/items/sample")[1]["cache"], "hit")
                        checkout = {"id": "demo-order", "sku": "sample", "quantity": 2}
                        request_id = f"shop-{profile}-checkout"
                        status, order = request(19780, "/checkout", checkout, {"X-Request-Id": request_id})
                        self.assertEqual((status, order["totalCents"]), (201, 2 * price))
                        self.assertEqual(request(19781, "/orders/demo-order")[1], order)
                        self.assertEqual(request(19780, "/checkout", checkout)[1], order)
                        self.assertEqual(request(19784, "/stock/sample")[1]["available"], 8)
                        self.assertEqual(request(19780, "/metrics")[1], {"checkouts": 2})
                        with self.assertRaises(HTTPError) as rejected:
                            request(19780, "/checkout", {**checkout, "id": "too-many", "quantity": 9})
                        rejected.exception.close()
                        self.assertEqual(rejected.exception.code, 409)
                        deadline = time.monotonic() + 20
                        while True:
                            try:
                                delivery = request(19780, "/deliveries/demo-order")[1]
                                break
                            except HTTPError as error:
                                error.close()
                                if error.code != 404 or time.monotonic() >= deadline:
                                    raise
                                time.sleep(0.25)
                        self.assertEqual((delivery["status"], delivery["order"]), ("delivered", order))
                        redis = _docker(["ps", "-q", "--filter", f"label=com.docker.compose.project={name}",
                                         "--filter", "label=com.docker.compose.service=redis"])
                        self.assertEqual(_docker(["exec", redis, "redis-cli", "GET", counter_key]), "2")
                        for key, ttl in (("shop:catalog:sample", 75), ("shop:delivery:demo-order", 300)):
                            remaining = int(_docker(["exec", redis, "redis-cli", "TTL", key]))
                            self.assertGreater(remaining, ttl - 40)
                            self.assertLessEqual(remaining, ttl)

                        expected_logs = {(service, "http_request")
                                         for service in ("storefront", "orders", "catalog", "inventory")}
                        expected_logs.update({("orders", "order_published"), ("notifications", "notification_stored")})
                        query = '{app="injector-shop"} | json | requestId="' + request_id + '"'
                        route = "/loki/api/v1/query_range?" + urlencode({"query": query})
                        deadline = time.monotonic() + 15
                        while True:
                            _, logs = request(19764, route)
                            events = {(stream["stream"]["service"], json.loads(line)["event"])
                                      for stream in logs["data"]["result"] for _, line in stream["values"]}
                            if expected_logs <= events or time.monotonic() >= deadline:
                                break
                            time.sleep(0.25)
                        self.assertEqual(expected_logs - events, set())
                stop(project)
                output = project / ".local" / "quote.json"
                result = observe_http(project, "storefront", "mock", project / "scenarios" / "quote.json", output)
                self.assertEqual((result["coverage"], result["calls"]), ("observed", 1))
                recording = json.loads(output.read_bytes())
                self.assertEqual(recording["calls"][0]["responseFields"], {"/source": "wiremock", "/unitCents": mock_price})
                self.assertFalse((runtime_directory(project) / "session.json").exists())
            finally:
                stop(project)
                label = f"label=com.docker.compose.project={name}"
                networks = _docker(["network", "ls", "-q", "--filter", label]).split()
                if networks:
                    _docker(["network", "rm", *networks])
                self.assertFalse(_docker(["ps", "-aq", "--filter", label]))
