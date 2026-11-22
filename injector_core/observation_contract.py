"""Versioned files exchanged by the local recorder and Verifier."""
import json
import math

from jsonschema import Draft202012Validator

from .registry import RegistryError, SCHEMA_PATH, _parse_json

MAX_OBSERVATION_BYTES = 2 * 1024 * 1024
_SCHEMA = json.loads(SCHEMA_PATH.with_name("http-observation-v1.schema.json").read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA)


def _document_name(kind):
    return "verification suite" if kind == "suite" else f"HTTP {kind}"


def validate_document(data, kind):
    trace = isinstance(data, dict) and data.get("schemaVersion") == 2
    definition = "trace" + kind.capitalize() if trace and kind in ("scenario", "observation") else kind
    error = next(_VALIDATOR.descend(data, _SCHEMA["$defs"][definition]), None)
    if error:
        location = "/".join(map(str, error.path)) or "document"
        raise RegistryError(f"invalid {_document_name(kind)} at {location}")
    if kind == "scenario" and trace:
        trace_options = data["trace"]
        event_checks = trace_options.get("eventCounts", [])
        identifiers = [check["id"] for checks in (data.get("stateChecks", []), event_checks)
                       for check in checks]
        if "response" in identifiers or len(set(identifiers)) != len(identifiers):
            raise RegistryError("scenario check IDs must be unique and cannot use 'response'")
        if trace_options.get("settleSeconds", 0) >= trace_options["timeoutSeconds"]:
            raise RegistryError("trace settleSeconds must be less than timeoutSeconds")
        if len({tuple(sorted(check["match"].items())) for check in event_checks}) != len(event_checks):
            raise RegistryError("trace event count selectors must be unique")
        if any(check["count"] == 0 and check["match"] in trace_options["requiredEvents"] for check in event_checks):
            raise RegistryError("a required trace event cannot have a count of zero")
        if len(set(data.get("targetFields", [])) | data.get("expect", {}).get("fields", {}).keys()) > 16:
            raise RegistryError("too many target response fields")
    if kind == "observation":
        fields = [(data["target"] or {}).get("fields", {})] + [call[key] for call in data.get("calls", [])
                                               for key in ("requestFields", "responseFields")]
        fields.extend(check[key].get("fields", {}) for check in data.get("checks", [])
                      for key in ("actual", "expected") if key in check)
        if any(isinstance(value, float) and not math.isfinite(value)
               for values in fields for value in values.values()):
            raise RegistryError("invalid HTTP observation numeric field")
        if trace:
            ids = [check["id"] for check in data.get("checks", [])]
            if len(set(ids)) != len(ids):
                raise RegistryError("trace observation has duplicate check IDs")
            services = {data["targetNode"], *(event["service"] for event in data["events"]),
                        *(event["service"] for event in data["missingEvents"])}
            if not services <= data["variants"].keys():
                raise RegistryError("trace service is outside the selected variants")
        elif not all(data["edge"][key] in data["variants"] for key in ("caller", "dependency")):
            raise RegistryError("observation edge is outside the selected variants")
    return data


def decode_document(content, kind):
    if not isinstance(content, str):
        raise RegistryError(f"{_document_name(kind)} must be JSON text")
    if len(content.encode("utf-8")) > MAX_OBSERVATION_BYTES:
        raise RegistryError(f"{_document_name(kind)} exceeds the 2 MiB file limit")
    return validate_document(_parse_json(content), kind)


def read_document(path, kind):
    if not path.is_file():
        raise RegistryError(f"select an existing {_document_name(kind)} file")
    with path.open("rb") as stream:
        content = stream.read(MAX_OBSERVATION_BYTES + 1)
    if len(content) > MAX_OBSERVATION_BYTES:
        raise RegistryError(f"{_document_name(kind)} exceeds the 2 MiB file limit")
    return decode_document(content.decode("utf-8"), kind)
