"""Versioned files exchanged by the local recorder and Verifier."""
import json
import math

from jsonschema import Draft202012Validator

from .registry import RegistryError, SCHEMA_PATH, _parse_json

MAX_OBSERVATION_BYTES = 2 * 1024 * 1024
_SCHEMA = json.loads(SCHEMA_PATH.with_name("http-observation-v1.schema.json").read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA)


def validate_document(data, kind):
    trace = isinstance(data, dict) and data.get("schemaVersion") == 2
    definition = "trace" + kind.capitalize() if trace and kind in ("scenario", "observation") else kind
    error = next(_VALIDATOR.descend(data, _SCHEMA["$defs"][definition]), None)
    if error:
        location = "/".join(map(str, error.path)) or "document"
        raise RegistryError(f"invalid HTTP {kind} at {location}")
    if kind == "scenario" and trace:
        identifiers = [check["id"] for check in data.get("stateChecks", [])]
        if "response" in identifiers or len(set(identifiers)) != len(identifiers):
            raise RegistryError("state check IDs must be unique and cannot use 'response'")
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
            services = {data["targetNode"], *(event["service"] for event in data["events"]),
                        *(event["service"] for event in data["missingEvents"])}
            if not services <= data["variants"].keys():
                raise RegistryError("trace service is outside the selected variants")
        elif not all(data["edge"][key] in data["variants"] for key in ("caller", "dependency")):
            raise RegistryError("observation edge is outside the selected variants")
    return data


def decode_document(content, kind):
    if not isinstance(content, str):
        raise RegistryError(f"HTTP {kind} must be JSON text")
    if len(content.encode("utf-8")) > MAX_OBSERVATION_BYTES:
        raise RegistryError(f"HTTP {kind} exceeds the 2 MiB file limit")
    return validate_document(_parse_json(content), kind)


def read_document(path, kind):
    if not path.is_file():
        raise RegistryError(f"select an existing HTTP {kind} file")
    with path.open("rb") as stream:
        content = stream.read(MAX_OBSERVATION_BYTES + 1)
    if len(content) > MAX_OBSERVATION_BYTES:
        raise RegistryError(f"HTTP {kind} exceeds the 2 MiB file limit")
    return decode_document(content.decode("utf-8"), kind)
