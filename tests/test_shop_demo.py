import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import time
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

import yaml

from injector_core.observation import observe_http
from injector_core.registry import runtime_directory
from injector_core.runtime import _docker, prepare, select_plan, stop
from test_runtime import free_port


DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo" / "monorepo"


class ShopPlanTests(unittest.TestCase):
    def test_profiles_preserve_shared_dependencies_and_switch_pricing(self):
        expected = ["pricing", "redis", "catalog", "postgres", "inventory", "kafka", "orders",
                    "notifications", "storefront"]
        for profile, order in (("real", ["pricing-db", *expected]), ("mock", expected)):
            with self.subTest(profile=profile):
                _, plan = select_plan(DEMO, "storefront", profile)
                self.assertEqual(plan["order"], order)
                steps = {step["node"]: step for step in plan["steps"]}
                self.assertEqual(steps["orders"]["dependencies"], ["catalog", "inventory", "postgres", "kafka"])
                self.assertEqual(steps["notifications"]["dependencies"], ["kafka", "redis"])
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
    def test_checkout_profiles_and_http_observation(self):
        self.assertTrue((DEMO / "services" / "storefront" / "build" / "install" / "storefront" / "lib").is_dir(),
                        "run the shop installDist task first")
        name = "injector-shop-test-" + uuid4().hex[:10]
        with TemporaryDirectory() as temporary:
            project = Path(temporary).resolve() / "shop checkout"
            ports = copy_with_isolated_ports(project, name)
            opener = build_opener(ProxyHandler({}))

            def request(port, route, data=None):
                body = json.dumps(data).encode("utf-8") if data is not None else None
                uri = f"http://127.0.0.1:{ports[port]}{route}"
                with opener.open(Request(uri, data=body, headers={"Content-Type": "application/json"}), timeout=15) as response:
                    return response.status, json.load(response)

            try:
                for profile, source, price in (("real", "postgres", 1299), ("mock", "wiremock", 999)):
                    with self.subTest(profile=profile):
                        result = prepare(project, "storefront", profile)
                        self.assertEqual("pricing-db" in result["order"], profile == "real")
                        quote = request(19780, "/items/sample")[1]
                        self.assertEqual((quote["source"], quote["unitCents"], quote["cache"]), (source, price, "miss"))
                        self.assertEqual(request(19780, "/items/sample")[1]["cache"], "hit")
                        checkout = {"id": "demo-order", "sku": "sample", "quantity": 2}
                        status, order = request(19780, "/checkout", checkout)
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
                stop(project)
                output = project / ".local" / "quote.json"
                result = observe_http(project, "storefront", "mock", project / "scenarios" / "quote.json", output)
                self.assertEqual((result["coverage"], result["calls"]), ("observed", 1))
                recording = json.loads(output.read_bytes())
                self.assertEqual(recording["calls"][0]["responseFields"], {"/source": "wiremock", "/unitCents": 999})
                self.assertFalse((runtime_directory(project) / "session.json").exists())
            finally:
                stop(project)
                label = f"label=com.docker.compose.project={name}"
                networks = _docker(["network", "ls", "-q", "--filter", label]).split()
                if networks:
                    _docker(["network", "rm", *networks])
                self.assertFalse(_docker(["ps", "-aq", "--filter", label]))
