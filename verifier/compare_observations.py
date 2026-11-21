"""Compare recorded HTTP behavior using the shared artifact contract."""
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


def compare_observations(baseline, candidate):
    validate_document(baseline, "observation")
    validate_document(candidate, "observation")
    keys = ("scenario", "scenarioDigest", "profile", "variants", "edge")
    if any(baseline[key] != candidate[key] for key in keys):
        return {"verdict": "INCONCLUSIVE", "reason": "scenario, profile, variants or edge differ"}
    result = {"edge": baseline["edge"], "profile": baseline["profile"], "variants": baseline["variants"]}
    compared = ("coverage", "target", "calls")
    for name, document in (("baseline", baseline), ("candidate", candidate)):
        result[name] = {key: document[key] for key in compared}
    if any(document["coverage"] != "observed" for document in (baseline, candidate)):
        return {**result, "verdict": "INCONCLUSIVE", "reason": "at least one recording has missing or incomplete calls"}
    changes = list(_differences(result["baseline"], result["candidate"]))
    return {**result, "verdict": "FAIL" if changes else "PASS", "changes": changes[:50],
            "changeCount": len(changes)}


def compare_files(baseline, candidate):
    return compare_observations(read_document(Path(baseline), "observation"),
                                read_document(Path(candidate), "observation"))
