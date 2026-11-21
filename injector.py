"""Injector CLI for the demo runner and runtime registry inspection."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
DEMO = ROOT / "examples/demo"
CONFIG = DEMO / "config/project.json"
INFRA = ("postgres", "redis", "kafka")


def resolve(profile, with_vault=False, vault_service=None):
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    selected = config["profiles"][profile]
    env = {**config["env"], **selected["env"]}
    if with_vault:
        service = config["vaultMock"]["defaultService"] if vault_service is None else vault_service
        if not re.fullmatch(r"[a-z][a-z0-9-]*", service):
            raise ValueError("Vault service name must contain lowercase letters, digits, and hyphens and start with a letter")
        env.update(config["vaultMock"]["env"])
        env["VAULT_PATH"] = f"{config['vaultMock']['mount']}/data/{service}"
    # VM options remain ordered; the sample profiles define distinct -D keys.
    options = config["vmOptions"] + selected["vmOptions"]
    return config, selected["dependency"], env, options


def generate(profile, with_vault=False, vault_service=None):
    config, dependency, env, options = resolve(profile, with_vault, vault_service)
    component = ET.Element("component", name="ProjectRunConfigurationManager")
    run = ET.SubElement(component, "configuration", default="false",
                        name=f"Injector-{profile}", type="Application", factoryName="Application")
    ET.SubElement(run, "option", name="MAIN_CLASS_NAME", value=config["mainClass"])
    ET.SubElement(run, "module", name=config["module"])
    # Quote each complete argument, including values containing whitespace.
    vm = " ".join('"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
                  for value in options)
    ET.SubElement(run, "option", name="VM_PARAMETERS", value=vm)
    ET.SubElement(run, "option", name="WORKING_DIRECTORY", value="$PROJECT_DIR$")
    envs = ET.SubElement(run, "envs")
    for key, value in sorted(env.items()):
        ET.SubElement(envs, "env", name=key, value=value)
    method = ET.SubElement(run, "method", v="2")
    ET.SubElement(method, "option", name="Make", enabled="true")
    ET.indent(component)
    destination = DEMO / ".run" / f"Injector-{profile}.run.xml"
    destination.parent.mkdir(exist_ok=True)
    ET.ElementTree(component).write(destination, encoding="utf-8", xml_declaration=True)

    # Docker and IntelliJ use the same resolved config; only network addresses differ.
    container_env = {**env, "APP_BIND": "0.0.0.0",
                     "CATALOG_URL": "http://wiremock:8080" if dependency == "wiremock"
                     else "http://catalog:18082",
                     "DB_URL": "jdbc:postgresql://postgres:5432/demo",
                     "REDIS_HOST": "redis", "REDIS_PORT": "6379",
                     "KAFKA_BOOTSTRAP_SERVERS": "kafka:9092"}
    if with_vault:
        container_env["VAULT_ADDR"] = config["vaultMock"]["containerAddress"]
    override = {"services": {"main": {"environment": container_env,
                                      "command": options + [config["mainClass"]]}}}
    local = DEMO / ".local"
    local.mkdir(exist_ok=True)
    (local / f"compose-{profile}.json").write_text(json.dumps(override, indent=2), encoding="utf-8")
    return destination


def compose(*arguments, profile=None):
    command = ["docker", "compose", "-p", "injector-poc", "-f", str(DEMO / "docker/compose.yaml")]
    if profile:
        command += ["-f", str(DEMO / ".local" / f"compose-{profile}.json")]
    subprocess.run(command + list(arguments), cwd=DEMO, check=True)


def compile_java():
    destination = DEMO / "target/classes"
    destination.mkdir(parents=True, exist_ok=True)
    sources = sorted((DEMO / "src/main/java").rglob("*.java"))
    subprocess.run(["javac", "--release", "17", "-encoding", "UTF-8", "-d", str(destination),
                    *map(str, sources)], check=True, cwd=DEMO)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "generate", "up", "down", "run", "validate", "resolve", "render",
                                            "vault-demo", "check", "prepare", "stop", "serve", "hosts", "draft-check", "draft-convert",
                                            "ide-tool", "observe-http", "compare-http", "compare-worktrees"))
    parser.add_argument("target", nargs="?", help="application ID, draft path, or hosts action")
    parser.add_argument("--variant", action="append", default=[], metavar="NODE=VARIANT")
    parser.add_argument("--mode", choices=("dummy", "real"), help="prepare using a matching registry profile")
    parser.add_argument("--port", type=int, default=18770, help="local UI port (serve only)")
    parser.add_argument("--open", action="store_true", help="open the local UI in a browser")
    parser.add_argument("--profile", help="profile name; legacy demo commands default to mock")
    parser.add_argument("--project", type=Path, help="source project or worktree directory")
    parser.add_argument("--registry", type=Path, help="registry file or a directory containing registry.json")
    parser.add_argument("--output", type=Path, help="new file for draft conversion or observe-http, new directory for compare-worktrees")
    parser.add_argument("--scenario", type=Path, help="scenario JSON for observe-http or compare-worktrees")
    parser.add_argument("--candidate", type=Path, help="current observation file for compare-http")
    parser.add_argument("--candidate-project", type=Path, help="candidate checkout directory for compare-worktrees")
    parser.add_argument("--expected-config", help="IntelliJ configuration fingerprint for a before-launch prepare")
    parser.add_argument("--node", help="node to resolve or render")
    parser.add_argument("--infra", nargs="*", choices=INFRA, default=[])
    parser.add_argument("--main-docker", action="store_true", help="also start the main app in Docker (up only)")
    parser.add_argument("--with-vault", action="store_true", help="include the local Vault API mock in demo setup")
    parser.add_argument("--vault-service", help="service name for the local Vault secret path; enables the Vault mock")
    args = parser.parse_args()
    if args.expected_config is not None and (args.command != "prepare" or not args.expected_config):
        parser.error("--expected-config requires prepare and a configuration fingerprint")
    if args.output and args.command not in ("draft-convert", "observe-http", "compare-worktrees"):
        parser.error("--output requires draft-convert, observe-http or compare-worktrees")
    if args.scenario and args.command not in ("observe-http", "compare-worktrees"):
        parser.error("--scenario requires observe-http or compare-worktrees")
    if args.candidate and args.command != "compare-http":
        parser.error("--candidate requires compare-http")
    if args.candidate_project and args.command != "compare-worktrees":
        parser.error("--candidate-project requires compare-worktrees")
    if args.command in ("observe-http", "compare-http", "compare-worktrees"):
        from injector_core.registry import RegistryError
        try:
            if args.command == "observe-http":
                if not (args.target and args.project and args.profile and args.scenario and args.output):
                    parser.error("observe-http requires an app ID, --project, --profile, --scenario and --output")
                if args.variant or args.mode:
                    parser.error("observe-http uses the selections from the specified profile")
                from injector_core.observation import observe_http
                result = observe_http(args.project, args.target, args.profile, args.scenario, args.output,
                                      registry=args.registry)
            elif args.command == "compare-http":
                if not (args.target and args.candidate):
                    parser.error("compare-http requires a baseline file and --candidate")
                from verifier.compare_observations import compare_files
                result = compare_files(args.target, args.candidate)
            else:
                if not (args.target and args.project and args.candidate_project and args.profile and args.scenario and args.output):
                    parser.error("compare-worktrees requires an app ID, --project, --candidate-project, --profile, --scenario and --output")
                if args.variant or args.mode or args.node or args.open or args.infra or args.main_docker or args.with_vault or args.vault_service:
                    parser.error("compare-worktrees uses the selections from the specified profile")
                from injector_core.observation import compare_worktrees
                result = compare_worktrees(args.project, args.candidate_project, args.target, args.profile,
                                           args.scenario, args.output, registry=args.registry,
                                           emit=lambda side: print(f"Recording {side} checkout", file=sys.stderr, flush=True))
            print(json.dumps(result, indent=2))
            if args.command != "observe-http":
                parser.exit({"PASS": 0, "FAIL": 1, "INCONCLUSIVE": 2}[result["verdict"]])
        except (ValueError, OSError, RecursionError) as error:
            parser.exit(2, f"Observation failed: {error}\n" if isinstance(error, RegistryError)
                        else "Observation failed: cannot read or write the HTTP artifact\n")
        except KeyboardInterrupt:
            parser.exit(130, "HTTP observation interrupted\n")
        return
    if args.command in ("draft-check", "draft-convert"):
        if not args.target or (args.command == "draft-convert" and not (args.project and args.output)):
            parser.error("provide a draft path; draft-convert also requires --project and --output")
        from injector_core.registration import run_registration
        from injector_core.registry import RegistryError
        try:
            print(json.dumps(run_registration(args.command, args.target, args.project, args.output), indent=2))
        except RegistryError as error:
            parser.exit(1, f"Invalid registration: {error}\n")
        except (OSError, UnicodeError, RecursionError):
            parser.exit(1, "Injector failed: cannot read the draft or write the candidate registry\n")
        return
    if args.registry is not None and (args.project is None or args.command not in
            ("validate", "resolve", "render", "plan", "check", "prepare", "stop", "serve", "hosts", "ide-tool")):
        parser.error("--registry requires --project and a registry command")
    if args.variant and (args.command not in ("check", "prepare", "plan", "ide-tool") or not args.target):
        parser.error("--variant requires check, prepare, plan or ide-tool with an application ID")
    if args.command == "ide-tool":
        if not (args.target and args.project and args.profile) or args.mode or args.node or args.open or args.infra \
                or args.main_docker or args.with_vault or args.vault_service:
            parser.error("ide-tool requires an application ID, --project and --profile")
        from injector_core.runtime import ide_tool, parse_variants
        from injector_core.registry import RegistryError
        try:
            print(json.dumps(ide_tool(args.project, args.target, args.profile, registry=args.registry,
                                      variants=parse_variants(args.variant)), indent=2))
        except (RegistryError, OSError) as error:
            parser.exit(1, f"Injector failed: {error}\n" if isinstance(error, RegistryError)
                        else "Injector failed: cannot generate IntelliJ configuration\n")
        return
    if args.command == "hosts":
        if args.target not in ("preview", "apply", "remove"):
            parser.error("hosts requires preview, apply, or remove")
        if args.mode or args.profile or args.infra or args.main_docker or args.with_vault or args.vault_service or args.node or args.open:
            parser.error("hosts accepts --project and --registry")
        from injector_core.hostnames import manage_hosts, name_mappings
        from injector_core.registry import RegistryError, load_registry
        project = args.project or Path.cwd()
        try:
            mappings = {} if args.target == "remove" else name_mappings(load_registry(project, registry=args.registry))
            print(json.dumps(manage_hosts(project, mappings, args.target), indent=2))
        except RegistryError as error:
            parser.exit(1, f"Injector failed: {error}\n")
        except OSError:
            parser.exit(1, "Injector failed: could not read or update the hosts file\n")
        return
    if args.target and args.command not in ("check", "prepare") and not (args.command == "plan" and args.project):
        parser.error("target requires check, prepare or plan with --project")
    if args.mode and args.command != "prepare":
        parser.error("--mode is supported only with prepare")
    if args.command in ("check", "prepare", "stop", "serve"):
        if args.infra or args.main_docker or args.with_vault or args.vault_service or args.node:
            parser.error("check, prepare, stop and serve do not accept legacy demo options")
        from injector_core.registry import RegistryError
        try:
            if args.command == "check":
                if not (args.target and args.profile) or args.open:
                    parser.error("check requires an application ID and --profile")
                from injector_core.runtime import check_requirements, parse_variants
                result = check_requirements(args.project or Path.cwd(), args.target, args.profile,
                                            variants=parse_variants(args.variant), registry=args.registry)
                print(json.dumps(result, indent=2))
            elif args.command == "serve":
                from injector_core.web import serve
                serve(args.project or DEMO, args.port, args.open, registry=args.registry,
                      restore_selection=args.project is None)
            elif args.command == "stop":
                from injector_core.runtime import stop
                print(json.dumps(stop(args.project or Path.cwd(), registry=args.registry), indent=2))
            else:
                if not args.target:
                    parser.error("prepare requires an application ID")
                from injector_core.runtime import parse_variants, prepare
                result = prepare(args.project or Path.cwd(), args.target, args.profile, args.mode,
                                 emit=lambda event: print(json.dumps(event), flush=True),
                                 variants=parse_variants(args.variant), registry=args.registry,
                                 before_launch=args.expected_config)
                print(json.dumps(result, indent=2))
        except (RegistryError, OSError) as error:
            parser.exit(1, f"Injector failed: {error}\n" if isinstance(error, RegistryError) else "Injector failed: local runtime operation failed\n")
        except KeyboardInterrupt:
            parser.exit(130, "Injector operation interrupted\n")
        return
    if args.command in ("validate", "resolve", "render") or (args.command == "plan" and args.project is not None):
        if args.project is None or args.infra or args.main_docker or args.with_vault or args.vault_service is not None:
            parser.error("registry commands require --project and do not accept demo execution options")
        if args.command in ("resolve", "render") and (not args.node or not args.profile):
            parser.error("resolve and render require --node and --profile")
        if args.command == "plan" and not args.profile:
            parser.error("registry plan requires --profile")
        if args.command not in ("resolve", "render") and args.node:
            parser.error("--node is supported only with resolve or render")
        from injector_core.registry import RegistryError, load_registry
        try:
            if args.command == "plan" and args.target:
                from injector_core.runtime import parse_variants, select_plan
                _, plan = select_plan(args.project, args.target, args.profile, variants=parse_variants(args.variant),
                                      registry=args.registry)
                print(json.dumps(plan, indent=2))
                return
            data = load_registry(args.project, args.profile, registry=args.registry)
            if args.command == "render":
                from injector_core.rendering import render_node
                print(json.dumps(render_node(data, args.project, args.profile, args.node, registry=args.registry).describe(), indent=2))
                return
            if args.command == "plan":
                from injector_core.planning import build_plan
                print(json.dumps(build_plan(data, args.profile), indent=2))
                return
            if args.command == "resolve":
                from injector_core.resolution import resolve_node
                print(json.dumps(resolve_node(data, args.profile, args.node).describe(), indent=2))
                return
            from injector_core.planning import validate_plans
            validate_plans(data, args.profile)
        except RegistryError as error:
            parser.exit(1, f"Invalid registry: {error}\n")
        profiles = [args.profile] if args.profile else list(data["profiles"])
        print(json.dumps({"status": "valid", "schemaVersion": data["schemaVersion"],
                          "nodes": len(data["nodes"]), "profiles": profiles}, indent=2))
        return
    if args.project is not None or args.node is not None:
        parser.error("project options require validate, resolve, render, or plan")
    args.profile = args.profile or "mock"
    if args.profile not in ("mock", "real"):
        parser.error("legacy demo commands support only mock and real profiles")
    with_vault = args.with_vault or args.vault_service is not None or args.command == "vault-demo"
    if with_vault and args.command not in ("plan", "generate", "up", "run", "vault-demo"):
        parser.error("--with-vault is supported only with demo plan, generate, up, run, and vault-demo")
    try:
        config, dependency, env, options = resolve(args.profile, with_vault, args.vault_service)
    except ValueError as error:
        parser.error(str(error))
    if args.main_docker and args.command != "up":
        parser.error("--main-docker is supported only with up")
    if args.infra and args.command not in ("plan", "up"):
        parser.error("--infra is supported only with plan and up")
    if args.command == "plan":
        print(json.dumps({"project": config["project"], "profile": args.profile,
                          "dependency": dependency, "infrastructure": args.infra,
                          "auxiliaryServices": [config["vaultMock"]["service"]] if with_vault else [],
                          "environmentKeys": sorted(env), "vmOptionCount": len(options)}, indent=2))
    elif args.command == "generate":
        print(f"Generated {generate(args.profile, with_vault, args.vault_service).relative_to(ROOT)}")
    elif args.command == "up":
        generate(args.profile, with_vault, args.vault_service)
        services = [dependency, *args.infra]
        if with_vault:
            services.append(config["vaultMock"]["service"])
        if args.main_docker:
            services.append("main")
        compose("up", "-d", "--build", "--wait", "--wait-timeout", "180", *services,
                profile=args.profile)
        if args.main_docker:
            print("Main app ready: http://localhost:18080/demo")
        else:
            print(f"Dependencies ready. Start Injector-{args.profile} with Debug in IntelliJ.")
    elif args.command == "down":
        compose("down")
    elif args.command == "vault-demo":
        subprocess.run([sys.executable, str(DEMO / "vault_client.py")],
                       env={**os.environ, **env}, cwd=DEMO, check=True)
    elif args.command == "run":
        classes = compile_java()
        subprocess.run(["java", *options, "-cp", str(classes), config["mainClass"]],
                       env={**os.environ, **env}, cwd=DEMO, check=True)


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        print(f"Execution failed: {error}", file=sys.stderr)
        sys.exit(1)
