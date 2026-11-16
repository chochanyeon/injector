"""Small, standard-library-only POC runner. No IDE plugin required."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
DEMO = ROOT / "examples/demo"
CONFIG = DEMO / "config/project.json"
INFRA = ("postgres", "redis", "kafka")


def resolve(profile):
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    selected = config["profiles"][profile]
    env = {**config["env"], **selected["env"]}
    # VM options remain ordered; the sample profiles define distinct -D keys.
    options = config["vmOptions"] + selected["vmOptions"]
    return config, selected["dependency"], env, options


def generate(profile):
    config, dependency, env, options = resolve(profile)
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
    parser.add_argument("command", choices=("plan", "generate", "up", "down", "run"))
    parser.add_argument("--profile", choices=("mock", "real"), default="mock")
    parser.add_argument("--infra", nargs="*", choices=INFRA, default=[])
    parser.add_argument("--main-docker", action="store_true", help="also start the main app in Docker (up only)")
    args = parser.parse_args()
    config, dependency, env, options = resolve(args.profile)
    if args.main_docker and args.command != "up":
        parser.error("--main-docker is supported only with up")
    if args.infra and args.command not in ("plan", "up"):
        parser.error("--infra is supported only with plan and up")
    if args.command == "plan":
        print(json.dumps({"project": config["project"], "profile": args.profile,
                          "dependency": dependency, "infrastructure": args.infra,
                          "environmentKeys": sorted(env), "vmOptionCount": len(options)}, indent=2))
    elif args.command == "generate":
        print(f"Generated {generate(args.profile).relative_to(ROOT)}")
    elif args.command == "up":
        generate(args.profile)
        services = [dependency, *args.infra]
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
