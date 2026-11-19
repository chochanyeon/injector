"""Deterministic DFS postorder planning with no process or secret access."""
from .registry import RegistryError
from .resolution import selected_variant


def validate_plans(data, profile=None):
    for name in ([profile] if profile is not None else data["profiles"]):
        try:
            build_plan(data, name)
        except RegistryError as error:
            raise RegistryError(f"profiles/{name}: {error}") from error


def build_plan(data, profile_name):
    """Plan the profile's targets in declared dependency order."""
    if profile_name not in data["profiles"]:
        raise RegistryError(f"unknown profile: {profile_name}")
    nodes = {node["id"]: node for node in data["nodes"]}
    profile = data["profiles"][profile_name]
    states = {}
    active = []
    order = []
    for target in profile["targets"]:
        if target not in nodes or nodes[target]["kind"] != "application":
            raise RegistryError("plan target must name an application")
        stack = [(target, False)]
        while stack:
            node_id, exiting = stack.pop()
            if exiting:
                active.pop()
                states[node_id] = "done"
                order.append(node_id)
                continue
            if states.get(node_id) == "done":
                continue
            if states.get(node_id) == "visiting":
                cycle = [*active[active.index(node_id):], node_id]
                raise RegistryError("dependency cycle: " + " -> ".join(cycle))
            _, variant = selected_variant(nodes, profile, node_id)
            states[node_id] = "visiting"
            active.append(node_id)
            stack.append((node_id, True))
            stack.extend((dependency, False) for dependency in reversed(variant["dependencies"]))

    steps = []
    for node_id in order:
        name, variant = selected_variant(nodes, profile, node_id)
        steps.append({"node": node_id, "variant": name, "kind": nodes[node_id]["kind"],
                      "runner": variant["execution"]["type"],
                      "dependencies": list(variant["dependencies"])})
    return {"profile": profile_name, "targets": list(profile["targets"]), "order": order, "steps": steps}
