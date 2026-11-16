"""Generate local Spring configuration and an IntelliJ Application config."""
from dataclasses import dataclass, field
from pathlib import Path
import xml.etree.ElementTree as ET

import yaml

from .registry import RegistryError
from .resolution import ResolvedSettings, _spring_leaves, resolve_node, selected_variant


@dataclass
class RenderedConfig:
    yaml_path: Path
    run_path: Path
    settings: ResolvedSettings = field(repr=False)

    def describe(self):
        return {"springConfig": str(self.yaml_path), "runConfiguration": str(self.run_path),
                "settings": self.settings.describe()}


def _artifact_path(root, path):
    if not path.resolve().is_relative_to(root):
        raise RegistryError("generated configuration path escapes the project")
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise RegistryError("generated configuration path must not be a symbolic link")


def render_node(data, project, profile_name, node_id, environ=None):
    """Create owned artifacts only; never change source YAML or launch an app."""
    settings = resolve_node(data, profile_name, node_id, environ, defer_spring_env=True)
    nodes = {node["id"]: node for node in data["nodes"]}
    _, variant = selected_variant(nodes, data["profiles"][profile_name], node_id)
    execution = variant["execution"]
    if execution["type"] != "intellij":
        raise RegistryError("Spring rendering currently requires an IntelliJ execution definition")
    if not settings.spring_properties:
        raise RegistryError("Spring rendering requires springProperties")
    if any(" via environment/" in source for channel in ("env", "vmProperties")
           for source in settings.origins[channel].values()):
        raise RegistryError("render cannot persist environment references in env or VM properties; use runtime injection")
    managed = "spring.config.additional-location"
    if managed in settings.vm_properties or "SPRING_CONFIG_ADDITIONAL_LOCATION" in settings.env:
        raise RegistryError("generated Spring location conflicts with an existing setting")
    spring_names = [name for key, value in settings.spring_properties.items() for name in _spring_leaves(value, key)]
    if any(name.startswith("spring.config.") or name in ("spring.profiles.active", "spring.profiles.default", "spring.profiles.include")
           for name in spring_names):
        raise RegistryError("Spring bootstrap settings must use VM properties or environment")
    if "spring.application.json" in settings.vm_properties or "SPRING_APPLICATION_JSON" in settings.env:
        raise RegistryError("Spring rendering cannot combine an opaque application JSON override")

    root = Path(project).resolve()
    application = (root / execution["projectPath"]).resolve()
    if not application.is_relative_to(root) or not application.is_dir():
        raise RegistryError("IntelliJ projectPath must be an existing directory inside the project")
    yaml_path = root / ".local" / "injector" / profile_name / node_id / "spring-overrides.yml"
    run_path = application / ".run" / f"Injector-{profile_name}-{node_id}.run.xml"
    _artifact_path(root, yaml_path)
    _artifact_path(root, run_path)
    settings.vm_properties[managed] = yaml_path.as_uri()
    settings.origins["vmProperties"][managed] = "generated/spring-overrides.yml"

    component = ET.Element("component", name="ProjectRunConfigurationManager")
    run = ET.SubElement(component, "configuration", default="false", name=f"Injector-{profile_name}-{node_id}",
                        type="Application", factoryName="Application")
    ET.SubElement(run, "option", name="MAIN_CLASS_NAME", value=execution["mainClass"])
    ET.SubElement(run, "module", name=execution["module"])
    arguments = " ".join('"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
                         for value in settings.jvm_arguments())
    ET.SubElement(run, "option", name="VM_PARAMETERS", value=arguments)
    ET.SubElement(run, "option", name="WORKING_DIRECTORY", value="$PROJECT_DIR$")
    envs = ET.SubElement(run, "envs")
    for key, value in settings.env.items():
        ET.SubElement(envs, "env", name=key, value=value)
    method = ET.SubElement(run, "method", v="2")
    ET.SubElement(method, "option", name="Make", enabled="true")
    ET.indent(component)
    content = yaml.safe_dump(settings.spring_properties, allow_unicode=True, sort_keys=False)
    try:
        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        run_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_path.write_text(content, encoding="utf-8")
        ET.ElementTree(component).write(run_path, encoding="utf-8", xml_declaration=True)
    except OSError as error:
        raise RegistryError("cannot write generated Spring configuration") from error
    return RenderedConfig(yaml_path, run_path, settings)
