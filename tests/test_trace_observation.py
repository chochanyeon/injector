import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from injector_core.observation_contract import read_document
from injector_core.registry import RegistryError
from injector_core.runtime import select_plan
from injector_core.trace_observation import TraceObservation
from test_http_observation import artifact
from verifier.compare_observations import compare_observations


DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo" / "monorepo"


class TraceObservationTests(unittest.TestCase):
    def test_independent_request_ids_and_event_order_do_not_change_the_verdict(self):
        scenario = read_document(DEMO / "scenarios" / "checkout-trace.json", "scenario")
        data, plan = select_plan(DEMO, "storefront", "mock")

        def capture(*, reverse=False, omit_consumer=False):
            observation = TraceObservation(scenario)
            observation._route(data, plan)
            request_id = None
            now = 0

            def exchange(endpoint, method, path, body=None, headers=(), **kwargs):
                nonlocal request_id
                if method == "POST":
                    request_id = dict(headers)["X-Request-Id"]
                    return 201, [("X-Request-Id", request_id)], b'{"id":"trace-order","totalCents":1998}'
                query = parse_qs(urlsplit(path).query)["query"][0]
                self.assertIn(f'requestId="{request_id}"', query)
                streams = []
                required = scenario["trace"]["requiredEvents"]
                for expected in reversed(required) if reverse else required:
                    service, event = expected["service"], expected["event"]
                    if omit_consumer and event == "kafka_consume":
                        continue
                    details = ({"method": "GET", "path": "/sample", "status": 200}
                               if event.startswith("http_") else {"topic": "shop.orders"})
                    if "dependency" in expected:
                        details["dependency"] = expected["dependency"]
                    details["privateField"] = "must stay out of the recording"
                    line = {"event": event, "requestId": request_id, "details": details}
                    streams.append({"stream": {"service": service}, "values": [
                        ["123", json.dumps(line)], ["124", json.dumps({**line, "requestId": "other-request"})]]})
                return 200, [], json.dumps({"status": "success",
                                            "data": {"resultType": "streams", "result": streams}}).encode()

            def sleep(seconds):
                nonlocal now
                now += seconds

            with patch("injector_core.trace_observation._exchange", side_effect=exchange), \
                    patch("injector_core.trace_observation.time.monotonic", side_effect=lambda: now), \
                    patch("injector_core.trace_observation.time.sleep", side_effect=sleep):
                recording = observation.capture(plan)
            self.assertNotIn(request_id, json.dumps(recording))
            self.assertNotIn("privateField", json.dumps(recording))
            return recording, request_id

        before, before_id = capture()
        after, after_id = capture(reverse=True)
        self.assertNotEqual(before_id, after_id)
        self.assertEqual(len(before["events"]), len(scenario["trace"]["requiredEvents"]))
        self.assertEqual(compare_observations(before, after)["verdict"], "PASS")

        after["events"].append(after["events"][0])
        self.assertEqual(compare_observations(before, after)["verdict"], "FAIL")
        missing, _ = capture(omit_consumer=True)
        self.assertEqual(missing["missingEvents"], [{"service": "notifications", "event": "kafka_consume"}])
        self.assertEqual(compare_observations(before, missing)["verdict"], "INCONCLUSIVE")
        self.assertEqual(compare_observations(artifact(), before)["verdict"], "INCONCLUSIVE")

    def test_checkout_checks_initial_state_and_asserts_persisted_effects(self):
        scenario = read_document(DEMO / "scenarios" / "checkout-evidence.json", "scenario")
        data, plan = select_plan(DEMO, "storefront", "mock")
        observation = TraceObservation(scenario)
        observation._route(data, plan)

        def capture(initial_stock=10, final_stock=8, *, delivery_unavailable=False):
            checkout_sent = False
            delivery_reads = 0
            now = 0

            def exchange(endpoint, method, path, body=None, headers=(), **kwargs):
                nonlocal checkout_sent, delivery_reads
                if method == "POST":
                    checkout_sent = True
                    return 201, list(headers), b'{"id":"trace-order","totalCents":1998}'
                if path.startswith("/stock/"):
                    return 200, [], json.dumps({"available": final_stock if checkout_sent else initial_stock}).encode()
                if path.startswith("/orders/"):
                    return ((200, [], b'{"sku":"sample","quantity":2,"totalCents":1998,"extra":"hidden"}')
                            if checkout_sent else (404, [], b""))
                if path.startswith("/deliveries/"):
                    delivery_reads += 1
                    if delivery_unavailable:
                        raise ConnectionError()
                    if delivery_reads == 1:
                        return 404, [], b""
                    return 200, [], b'{"status":"delivered","order":{"id":"trace-order"}}'
                self.fail(f"unexpected request {method} {path}")

            def sleep(seconds):
                nonlocal now
                now += seconds

            events = [dict(event, topic="shop.orders") if event["event"].startswith("kafka_") else
                      dict(event, method="GET", path="/sample", status=200)
                      for event in scenario["trace"]["requiredEvents"]]
            with patch("injector_core.trace_observation._exchange", side_effect=exchange), \
                    patch.object(observation, "_collect", return_value=(events, None)), \
                    patch("injector_core.trace_observation.time.monotonic", side_effect=lambda: now), \
                    patch("injector_core.trace_observation.time.sleep", side_effect=sleep):
                return observation.capture(plan), checkout_sent, delivery_reads

        passing, sent, delivery_reads = capture()
        self.assertTrue(sent)
        self.assertEqual(delivery_reads, 2)
        self.assertEqual(compare_observations(passing, passing)["verdict"], "PASS")
        self.assertNotIn("hidden", json.dumps(passing))
        failed, _, _ = capture(final_stock=6)
        self.assertEqual(compare_observations(failed, failed)["verdict"], "FAIL")
        self.assertEqual(compare_observations(failed, passing, prove_fix="final-stock")["verdict"], "PASS")
        self.assertEqual(compare_observations(failed, failed, prove_fix="final-stock")["verdict"], "FAIL")
        self.assertEqual(compare_observations(passing, passing, prove_fix="final-stock")["verdict"], "FAIL")
        check = next(check for check in failed["checks"] if check["id"] == "final-stock")
        self.assertEqual((check["expected"]["fields"], check["actual"]["fields"]), ({"/available": 8}, {"/available": 6}))
        skipped, sent, delivery_reads = capture(initial_stock=7)
        self.assertFalse(sent)
        self.assertEqual(delivery_reads, 0)
        self.assertIsNone(skipped["target"])
        self.assertEqual(compare_observations(passing, skipped)["verdict"], "INCONCLUSIVE")
        unavailable, _, _ = capture(delivery_unavailable=True)
        self.assertEqual(compare_observations(passing, unavailable)["verdict"], "INCONCLUSIVE")
        self.assertEqual(compare_observations(failed, unavailable, prove_fix="final-stock")["verdict"], "INCONCLUSIVE")

        scenario["stateChecks"][0]["node"] = "pricing-db"
        with self.assertRaisesRegex(RegistryError, "outside the target dependency plan"):
            TraceObservation(scenario)._route(data, plan)
