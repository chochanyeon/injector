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

    def jvm_arguments(self):
        return [*self.vm_options, *(f"-D{key}={value}" for key, value in self.vm_properties.items())]

    def describe(self):
        return {"node": self.node, "variant": self.variant,
                "env": {key: {"value": "<redacted>", "source": self.origins["env"][key]}
                        for key in self.env},
                "vmProperties": {key: {"value": "<redacted>", "source": self.origins["vmProperties"][key]}
                                 for key in self.vm_properties},
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


def resolve_node(data, profile_name, node_id, environ=None):
    """Accept a validated registry and return actual values plus provenance."""
    if profile_name not in data["profiles"]:
        raise RegistryError(f"unknown profile: {profile_name}")
    nodes = {node["id"]: node for node in data["nodes"]}
    profile = data["profiles"][profile_name]
    name, variant = selected_variant(nodes, profile, node_id)
    origins = {"env": {}, "vmProperties": {}, "vmOptions": []}
    maps = {"env": {}, "vmProperties": {}}
    options = []
    layers = [(data.get("defaults", {}), "defaults"),
              (variant, f"nodes/{node_id}/variants/{name}"),
              (profile.get("overrides", {}).get(node_id, {}), f"profiles/{profile_name}/overrides/{node_id}")]
    for layer, location in layers:
        for channel in maps:
            for key, value in layer.get(channel, {}).items():
                if channel == "vmProperties":
                    _property_key(key)
                maps[channel][key] = value
                origins[channel][key] = f"{location}/{channel}/{key}"
        for index, option in enumerate(layer.get("vmOptions", [])):
            if "\x00" in option:
                raise RegistryError("VM option contains a null character")
            options.append(option)
            origins["vmOptions"].append(f"{location}/vmOptions/{index}")

    for index, rule in enumerate(variant.get("injections", [])):
        channel = "env" if rule["channel"] == "environment" else "vmProperties"
        key = rule["key"]
        if channel == "vmProperties":
            _property_key(key)
        if key in maps[channel]:
            raise RegistryError(f"{node_id}: injection conflicts with an existing {channel} key")
        source = rule["source"]
        _, dependency = selected_variant(nodes, profile, source["node"])
        endpoint = dependency["endpoints"].get(source["endpoint"])
        if endpoint is None:
            raise RegistryError("injection endpoint is unavailable")
        maps[channel][key] = _address_value(endpoint, source)
        origins[channel][key] = f"nodes/{node_id}/variants/{name}/injections/{index}"

    environment = os.environ if environ is None else environ
    for channel, values in maps.items():
        for key, value in values.items():
            if isinstance(value, dict):
                reference = value["fromEnv"]
                if reference not in environment:
                    raise RegistryError(f"{node_id}: required environment reference is unavailable")
                value = environment[reference]
                origins[channel][key] += f" via environment/{reference}"
            if "\x00" in value:
                raise RegistryError(f"{node_id}: setting contains a null character")
            values[key] = value
    return ResolvedSettings(node_id, name, maps["env"], options, maps["vmProperties"], origins)
