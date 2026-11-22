"""Compare recorded dependency behavior using the shared artifact contract."""
import json
from pathlib import Path

from injector_core.observation_contract import read_document, validate_document


def _differences(before, after, pointer=""):
    if type(before) is type(after) and isinstance(before, dict):
        for key in sorted(before.keys() | after.keys()):
            path = pointer + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in before:
                yield {"path": path, "kind": "added"}
            elif key not in after:
                yield {"path": path, "kind": "removed"}
            else:
                yield from _differences(before[key], after[key], path)
    elif type(before) is type(after) and isinstance(before, list):
        for index, (left, right) in enumerate(zip(before, after)):
            yield from _differences(left, right, f"{pointer}/{index}")
        for index in range(min(len(before), len(after)), max(len(before), len(after))):
            yield {"path": f"{pointer}/{index}", "kind": "removed" if len(before) > len(after) else "added"}
    elif type(before) is not type(after) or before != after:
        yield {"path": pointer, "kind": "changed"}


def _prove_fix(baseline, candidate, check_id):
    before = next((check for check in baseline.get("checks", []) if check["id"] == check_id), None)
    after = next((check for check in candidate.get("checks", []) if check["id"] == check_id), None)
    if (before is None or after is None or before["when"] == "before"
            or (before["when"], before["expected"]) != (after["when"], after["expected"])):
        return "INCONCLUSIVE", "the same behavior check must be recorded on both sides"
    if before["verdict"] == "INCONCLUSIVE":
        return "INCONCLUSIVE", "the baseline behavior check could not be confirmed"
    if before["verdict"] == "PASS":
        return "FAIL", "the baseline did not reproduce the expected failure"
    if any(check["verdict"] == "FAIL" for check in candidate["checks"]):
        return "FAIL", "the candidate failed an expected behavior check"
    if candidate["coverage"] != "observed" or any(check["verdict"] != "PASS" for check in candidate["checks"]):
        return "INCONCLUSIVE", "the candidate has incomplete evidence"
    return "PASS", "the baseline reproduced the failure and the candidate passed"


def compare_observations(baseline, candidate, *, prove_fix=None):
    validate_document(baseline, "observation")
    validate_document(candidate, "observation")
    if baseline["schemaVersion"] != candidate["schemaVersion"]:
        return {"verdict": "INCONCLUSIVE", "reason": "observation formats differ"}
    trace = baseline["schemaVersion"] == 2
    location = "targetNode" if trace else "edge"
    keys = ("scenario", "scenarioDigest", "profile", "variants", location)
    if any(baseline[key] != candidate[key] for key in keys):
        scope = "target" if trace else "edge"
        return {"verdict": "INCONCLUSIVE", "reason": f"scenario, profile, variants or {scope} differ"}
    result = {location: baseline[location], "profile": baseline["profile"], "variants": baseline["variants"]}
    compared = ("coverage", "target", "events", "missingEvents") if trace else ("coverage", "target", "calls")
    for name, document in (("baseline", baseline), ("candidate", candidate)):
        result[name] = {key: document[key] for key in compared}
        if trace:
            result[name]["events"] = sorted(document["events"], key=lambda event: json.dumps(event, sort_keys=True))
            if "reason" in document:
                result[name]["reason"] = document["reason"]
            if "checks" in document:
                result[name]["checks"] = document["checks"]
    if prove_fix is not None:
        verdict, reason = _prove_fix(baseline, candidate, prove_fix)
        return {**result, "verdict": verdict, "reason": reason, "fixCheck": prove_fix}
    if any(check["verdict"] == "FAIL" for document in (baseline, candidate) for check in document.get("checks", [])):
        return {**result, "verdict": "FAIL", "reason": "at least one expected behavior check failed"}
    if any(document["coverage"] != "observed" for document in (baseline, candidate)):
        reason = ("at least one recording has incomplete coverage" if trace
                  else "at least one recording has missing or incomplete calls")
        return {**result, "verdict": "INCONCLUSIVE", "reason": reason}
    if any(check["verdict"] != "PASS"
           for document in (baseline, candidate) for check in document.get("checks", [])):
        return {**result, "verdict": "INCONCLUSIVE", "reason": "at least one behavior check could not be confirmed"}
    changes = list(_differences({key: result["baseline"][key] for key in compared},
                                {key: result["candidate"][key] for key in compared}))
    return {**result, "verdict": "FAIL" if changes else "PASS", "changes": changes[:50],
            "changeCount": len(changes)}


def compare_files(baseline, candidate, *, prove_fix=None):
    return compare_observations(read_document(Path(baseline), "observation"),
                                read_document(Path(candidate), "observation"), prove_fix=prove_fix)
