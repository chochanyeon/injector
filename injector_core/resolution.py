"""Resolve settings in memory; public descriptions never include values."""
from dataclasses import dataclass, field
import ipaddress
import os
import re
from urllib.parse import quote

from .registry import RegistryError


@dataclass
class ResolvedSettings:
    node: str
    variant: str
    env: dict = field(repr=False)
    vm_options: list = field(repr=False)
    vm_properties: dict = field(repr=False)
    origins: dict = field(repr=False)
    spring_properties: dict = field(default_factory=dict, repr=False)

    def jvm_arguments(self):
        return [*self.vm_options, *(f"-D{key}={value}" for key, value in self.vm_properties.items())]

    def describe(self):
        return {"node": self.node, "variant": self.variant,
                "env": {key: {"value": "<redacted>", "source": self.origins["env"][key]}
                        for key in self.env},
                "vmProperties": {key: {"value": "<redacted>", "source": self.origins["vmProperties"][key]}
                                 for key in self.vm_properties},
                "springProperties": {key: {"value": "<redacted>", "source": self.origins["springProperties"][key]}
                                     for key in self.spring_properties},
                "vmOptions": [{"index": index, "source": source}
                              for index, source in enumerate(self.origins["vmOptions"])]}


def selected_variant(nodes, profile, node_id):
    name = profile["selections"].get(node_id)
    if node_id not in nodes or name not in nodes[node_id]["variants"]:
        raise RegistryError(f"missing or invalid selection for {node_id}")
    return name, nodes[node_id]["variants"][name]


def _address_value(endpoint, source):
    address = endpoint["addresses"].get(source["context"])
    if address is None:
        raise RegistryError("injection address context is unavailable")
    host = address["host"]
    if host in ("0.0.0.0", "::", "*") or "%" in host:
        raise RegistryError("injection host must be a concrete destination")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if not all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
                   for label in host.removesuffix(".").split(".")):
            raise RegistryError("invalid injection hostname") from None
        authority = host
    else:
        authority = f"[{host}]" if ip.version == 6 else host
    component = source["component"]
    if component == "host":
        return host
    if component == "port":
        return str(address["port"])
    scheme = address.get("scheme", "")
    if not re.fullmatch(r"[a-z][a-z0-9+.-]*", scheme):
        raise RegistryError("URL injection requires a valid scheme")
    if endpoint["protocol"] in ("http", "https") and scheme != endpoint["protocol"]:
        raise RegistryError("URL scheme conflicts with endpoint protocol")
    path = address.get("path", "/")
    if any(character in path for character in ("?", "#", "\x00", "\r", "\n")):
        raise RegistryError("endpoint path must not contain query, fragment, or control characters")
    return f"{scheme}://{authority}:{address['port']}{quote(path, safe='/%')}"


def _property_key(key):
    if any(character in key for character in ("=", "\x00", "\n", "\r")):
        raise RegistryError("invalid VM property key")


def _resolve_value(value, environment, defer):
    references = []
    if isinstance(value, dict):
        if set(value) == {"fromEnv"}:
            reference = value["fromEnv"]
            if defer:
                return "${" + reference + "}", [reference]
            if reference not in environment:
                raise RegistryError("required environment reference is unavailable")
            value = environment[reference]
            references.append(reference)
        else:
            result = {}
            for key, child in value.items():
                result[key], names = _resolve_value(child, environment, defer)
                references.extend(names)
            return result, references
    elif isinstance(value, list):
        result = []
        for child in value:
            resolved, names = _resolve_value(child, environment, defer)
            result.append(resolved)
            references.extend(names)
        return result, references
    if isinstance(value, str) and "\x00" in value:
        raise RegistryError("setting contains a null character")
    return value, references


def _spring_leaves(value, prefix):
    if isinstance(value, dict) and value:
        return [name for key, child in value.items() for name in _spring_leaves(child, f"{prefix}.{key}")]
    if isinstance(value, list) and value:
        return [name for index, child in enumerate(value) for name in _spring_leaves(child, f"{prefix}[{index}]")]
    return [prefix]


def resolve_node(data, profile_name, node_id, environ=None, defer_spring_env=False, *, injection_urls=None):
    """Accept a validated registry and return actual values plus provenance."""
    if profile_name not in data["profiles"]:
        raise RegistryError(f"unknown profile: {profile_name}")
    nodes = {node["id"]: node for node in data["nodes"]}
    profile = data["profiles"][profile_name]
    name, variant = selected_variant(nodes, profile, node_id)
    origins = {"env": {}, "vmProperties": {}, "springProperties": {}, "vmOptions": []}
    maps = {"env": {}, "vmProperties": {}, "springProperties": {}}
    options = []
    layers = [(data.get("defaults", {}), "defaults"),
              (variant, f"nodes/{node_id}/variants/{name}"),
              (nodes[node_id].get("profileOverrides", {}).get(profile_name, {}),
               f"nodes/{node_id}/profileOverrides/{profile_name}"),
              (profile.get("overrides", {}).get(node_id, {}), f"profiles/{profile_name}/overrides/{node_id}")]
    for layer, location in layers:
        for channel in maps:
            for key, value in layer.get(channel, {}).items():
                if channel in ("vmProperties", "springProperties"):
                    _property_key(key)
                maps[channel][key] = value
                origins[channel][key] = f"{location}/{channel}/{key}"
        for index, option in enumerate(layer.get("vmOptions", [])):
            if "\x00" in option:
                raise RegistryError("VM option contains a null character")
            options.append(option)
            origins["vmOptions"].append(f"{location}/vmOptions/{index}")

    for index, rule in enumerate(variant.get("injections", [])):
        channel = {"environment": "env", "vmProperty": "vmProperties", "springProperty": "springProperties"}[rule["channel"]]
        key = rule["key"]
        if channel in ("vmProperties", "springProperties"):
            _property_key(key)
        if key in maps[channel]:
            raise RegistryError(f"{node_id}: injection conflicts with an existing {channel} key")
        source = rule["source"]
        _, dependency = selected_variant(nodes, profile, source["node"])
        endpoint = dependency["endpoints"].get(source["endpoint"])
        if endpoint is None:
            raise RegistryError("injection endpoint is unavailable")
        address = _address_value(endpoint, source)
        if injection_urls and source["context"] == "host" and source["component"] == "url":
            address = injection_urls.get((node_id, source["node"], source["endpoint"]), address)
        maps[channel][key] = address
        origins[channel][key] = f"nodes/{node_id}/variants/{name}/injections/{index}"

    environment = os.environ if environ is None else environ
    for channel, values in maps.items():
        for key, value in values.items():
            values[key], references = _resolve_value(value, environment, defer_spring_env and channel == "springProperties")
            if references:
                origins[channel][key] += " via " + ", ".join(f"environment/{reference}" for reference in references)
    spring_keys = list(maps["springProperties"])
    leaves = [leaf for key in spring_keys for leaf in _spring_leaves(maps["springProperties"][key], key)]
    if len(leaves) != len(set(leaves)):
        raise RegistryError("overlapping Spring property keys")
    for key in spring_keys:
        if any(other != key and (other.startswith(key + ".") or other.startswith(key + "[")) for other in spring_keys):
            raise RegistryError("overlapping Spring property keys")
        for leaf in _spring_leaves(maps["springProperties"][key], key):
            if leaf in maps["vmProperties"] or leaf.replace(".", "_").replace("-", "").upper() in maps["env"]:
                raise RegistryError("Spring property conflicts with a VM property or environment key")
    return ResolvedSettings(node_id, name, maps["env"], options, maps["vmProperties"], origins, maps["springProperties"])
