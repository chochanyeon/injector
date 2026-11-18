"""Generate local Spring configuration and an IntelliJ Application config."""
from dataclasses import dataclass, field
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import xml.etree.ElementTree as ET

import yaml

from .registry import RegistryError, _project_path, runtime_directory
from .resolution import ResolvedSettings, _spring_leaves, resolve_node, selected_variant


@dataclass
class RenderedConfig:
    yaml_path: Path | None
    run_path: Path
    settings: ResolvedSettings = field(repr=False)

    def describe(self):
        return {"springConfig": str(self.yaml_path) if self.yaml_path else None, "runConfiguration": str(self.run_path),
                "settings": self.settings.describe()}


def _artifact_path(root, path):
    if not path.resolve().is_relative_to(root):
        raise RegistryError("generated configuration path escapes the project")
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise RegistryError("generated configuration path must not be a symbolic link")


def render_node(data, project, profile_name, node_id, environ=None, *, allow_plain=False, registry=None):
    """Create owned artifacts only; never change source YAML or launch an app."""
    result, write = plan_render(data, project, profile_name, node_id, environ, allow_plain=allow_plain, registry=registry)
    write()
    return result


def _replace_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(content)
            handle.close()
            os.replace(temporary, path)
        finally:
            handle.close()
            temporary.unlink(missing_ok=True)


def plan_render(data, project, profile_name, node_id, environ=None, *, allow_plain=False, registry=None):
    """Validate and serialize the artifacts before touching an existing configuration."""
    settings = resolve_node(data, profile_name, node_id, environ, defer_spring_env=True)
    nodes = {node["id"]: node for node in data["nodes"]}
    _, variant = selected_variant(nodes, data["profiles"][profile_name], node_id)
    execution = variant["execution"]
    if execution["type"] != "intellij":
        raise RegistryError("Spring rendering currently requires an IntelliJ execution definition")
    if not settings.spring_properties and not allow_plain:
        raise RegistryError("Spring rendering requires springProperties")
    if any(" via environment/" in source for channel in ("env", "vmProperties")
           for source in settings.origins[channel].values()):
        raise RegistryError("render cannot persist environment references in env or VM properties; use runtime injection")
    managed = "spring.config.additional-location"
    if settings.spring_properties and (managed in settings.vm_properties or "SPRING_CONFIG_ADDITIONAL_LOCATION" in settings.env):
        raise RegistryError("generated Spring location conflicts with an existing setting")
    spring_names = [name for key, value in settings.spring_properties.items() for name in _spring_leaves(value, key)]
    if any(name.startswith("spring.config.") or name in ("spring.profiles.active", "spring.profiles.default", "spring.profiles.include")
           for name in spring_names):
        raise RegistryError("Spring bootstrap settings must use VM properties or environment")
    if settings.spring_properties and ("spring.application.json" in settings.vm_properties or "SPRING_APPLICATION_JSON" in settings.env):
        raise RegistryError("Spring rendering cannot combine an opaque application JSON override")

    root = Path(project).resolve()
    application = _project_path(root, execution["projectPath"], "IntelliJ projectPath").resolve()
    if not application.is_dir():
        raise RegistryError("IntelliJ projectPath must be an existing directory inside the project")
    directory = runtime_directory(root, registry)
    storage = Path(registry).resolve() if registry is not None else root
    yaml_path = directory / profile_name / node_id / "spring-overrides.yml"
    run_folder = directory / ".run" if registry is not None else application / ".run"
    run_path = run_folder / f"Injector-{profile_name}-{node_id}.run.xml"
    _artifact_path(storage, yaml_path)
    _artifact_path(storage, run_path)
    if settings.spring_properties:
        settings.vm_properties[managed] = yaml_path.as_uri()
        settings.origins["vmProperties"][managed] = "generated/spring-overrides.yml"
    else:
        yaml_path = None

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
    xml = ET.tostring(component, encoding="utf-8", xml_declaration=True)
    content = yaml.safe_dump(settings.spring_properties, allow_unicode=True, sort_keys=False).encode("utf-8")

    def write():
        try:
            _artifact_path(storage, run_path)
            if yaml_path:
                _artifact_path(storage, yaml_path)
                previous = yaml_path.read_bytes() if yaml_path.exists() else None
                _replace_file(yaml_path, content)
            try:
                _replace_file(run_path, xml)
            except OSError:
                if yaml_path:
                    if previous is None:
                        yaml_path.unlink()
                    else:
                        _replace_file(yaml_path, previous)
                raise
        except OSError as error:
            raise RegistryError("cannot write generated Spring configuration") from error

    return RenderedConfig(yaml_path, run_path, settings), write
