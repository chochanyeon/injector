"""Build fixtures and run the complete Injector and Verifier test environment."""
import argparse
from datetime import datetime, timezone
from hashlib import sha512
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener, urlopen
from uuid import uuid4
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "verifier"
SPRING_JAR = ROOT / "examples/spring-config/target/spring-config-probe-0.1.0.jar"
MAVEN_VERSION = "3.9.16"
MAVEN_SUM = ("ed41650d42485cfc243fad22158caf9cbb5dc408ce7a09ddb94dd42a019de929ca43065"
             "bfa450612cf12bf78b5cafa3884b96c090de326ff590448c933454af3")
PYTHON_TESTS = """
import sys
import unittest

tests = unittest.defaultTestLoader.discover('tests')
result = unittest.TextTestRunner(verbosity=2).run(tests)
if result.skipped:
    print('Full verification requires every Python test to run.', file=sys.stderr)
raise SystemExit(not result.wasSuccessful() or bool(result.skipped))
"""


def _tool(name):
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"Install {name} and put it on PATH.")
    return path


def _capture(arguments, env=None):
    return subprocess.check_output(arguments, cwd=ROOT, env=env, text=True, stderr=subprocess.STDOUT).strip()


class Verification:
    def __init__(self, output):
        self.output = output
        self.stages = []
        self.env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "PYTHONUNBUFFERED": "1"}

    def stage(self, name, action):
        filename = name + ".log"
        result = {"id": name, "status": "FAIL", "log": filename}
        self.stages.append(result)
        print(f"Running {name}", file=sys.stderr, flush=True)
        with (self.output / filename).open("x", encoding="utf-8") as log:
            try:
                action(log)
            except subprocess.CalledProcessError as error:
                result["exitCode"] = error.returncode
                if error.output:
                    print(error.output, file=log)
                print(f"Command exit status {error.returncode}", file=log)
            except (OSError, RuntimeError) as error:
                print(error, file=log)
            except KeyboardInterrupt:
                result["status"] = "INTERRUPTED"
                raise
            else:
                result.update(status="PASS", exitCode=0)
        print(f"{result['status']} {name}", file=sys.stderr, flush=True)
        return result["status"] == "PASS"

    def command(self, name, arguments, *, cwd=ROOT):
        return self.stage(name, lambda log: subprocess.run(arguments, cwd=cwd, env=self.env,
                                                         stdout=log, stderr=subprocess.STDOUT, check=True))

    def blocked(self, name, reason):
        self.stages.append({"id": name, "status": "NOT_RUN", "reason": reason})

    def preflight(self, log):
        if sys.version_info < (3, 10):
            raise RuntimeError("Use Python 3.10 or newer.")
        self.node = _tool("node")
        self.docker = _tool("docker")
        git = _tool("git")
        if os.name == "nt":
            git_root = Path(_capture([git, "--exec-path"])).parents[2]
            self.bash = git_root / "bin/bash.exe"
            if not self.bash.is_file():
                raise RuntimeError("Install Git for Windows with Git Bash.")
        else:
            self.bash = _tool("bash")
        java_home = self.env.get("JAVA_HOME")
        if not java_home:
            settings = _capture([_tool("java"), "-XshowSettings:properties", "-version"])
            match = re.search(r"^\s*java\.home = (.+)$", settings, flags=re.MULTILINE)
            if not match:
                raise RuntimeError("Set JAVA_HOME to a JDK 17 or newer.")
            java_home = match[1].strip()
        java_bin = Path(java_home) / "bin"
        suffix = ".exe" if os.name == "nt" else ""
        self.java = java_bin / ("java" + suffix)
        javac = java_bin / ("javac" + suffix)
        if not (self.java.is_file() and javac.is_file()):
            raise RuntimeError("Set JAVA_HOME to a JDK with java and javac.")
        version = _capture([javac, "-version"])
        match = re.search(r"javac (\d+)", version)
        if not match or int(match[1]) < 17:
            raise RuntimeError("Use JDK 17 or newer.")
        self.env.update(JAVA_HOME=str(java_bin.parent), PATH=str(java_bin) + os.pathsep + self.env.get("PATH", ""))
        for details in (version, _capture([self.node, "--version"]), _capture([self.docker, "compose", "version"])):
            print(details, file=log)
        if _capture([self.docker, "info", "--format", "{{.OSType}}"], self.env) != "linux":
            raise RuntimeError("Start Docker with a Linux container engine.")

    def maven(self, log):
        self.mvn = shutil.which("mvn")
        if self.mvn:
            print(self.mvn, file=log)
            return
        package = f"apache-maven-{MAVEN_VERSION}"
        file = f"{package}-bin.zip"
        address = f"https://archive.apache.org/dist/maven/maven-3/{MAVEN_VERSION}/binaries/{file}"
        with urlopen(address, timeout=60) as response:
            content = response.read(16 * 1024 * 1024)
        if sha512(content).hexdigest() != MAVEN_SUM:
            raise RuntimeError(f"Maven {MAVEN_VERSION} download checksum did not match.")
        archive = self.output / file
        archive.write_bytes(content)
        with ZipFile(archive) as distribution:
            distribution.extractall(self.output)
        bin_dir = self.output / package / "bin"
        self.mvn = bin_dir / ("mvn.cmd" if os.name == "nt" else "mvn")
        if os.name != "nt":
            self.mvn.chmod(0o755)
        print(f"Verified and extracted {file}", file=log)

    def python_tests(self, python):
        project = f"injector-test-{uuid4().hex[:12]}"
        compose = [self.docker, "compose", "-p", project, "-f", "examples/demo/docker/prepare-compose.yaml"]

        def start_vault(log):
            subprocess.run([*compose, "run", "-d", "--rm", "--no-deps", "--name", project,
                            "--publish", "127.0.0.1::8080", "vault-mock"],
                           cwd=ROOT, env=self.env, stdout=log, stderr=subprocess.STDOUT, check=True)
            address = _capture([self.docker, "port", project, "8080/tcp"], self.env)
            if not re.fullmatch(r"127\.0\.0\.1:\d+", address):
                raise RuntimeError("Could not identify WireMock's isolated listener.")
            url = "http://" + address
            opener = build_opener(ProxyHandler({}))
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                try:
                    with opener.open(url + "/__admin/health", timeout=2):
                        self.env["INJECTOR_TEST_VAULT_URL"] = url
                        print(f"WireMock ready at {url}", file=log)
                        return
                except OSError:
                    time.sleep(0.5)
            raise RuntimeError("WireMock Vault did not become ready.")

        try:
            if self.stage("vault-start", start_vault):
                self.env.update(INJECTOR_TEST_SHOP="1", INJECTOR_TEST_JAVA=str(self.java),
                                INJECTOR_TEST_SPRING_JAR=str(SPRING_JAR), INJECTOR_TEST_REPORTS=str(self.output))
                self.command("python-tests", [python, "-c", PYTHON_TESTS])
            else:
                self.blocked("python-tests", "WireMock Vault did not start")
        finally:
            self.command("vault-cleanup", [*compose, "down", "--remove-orphans"])

    def run(self):
        if not self.stage("preflight", self.preflight):
            return
        python = self.output / ("python/Scripts/python.exe" if os.name == "nt" else "python/bin/python")
        python_ready = self.command("python-env", [sys.executable, "-m", "venv", self.output / "python"])
        if python_ready:
            python_ready = self.command("python-dependencies", [python, "-m", "pip", "install", "--no-input",
                                                                "--disable-pip-version-check", "-r", "requirements.txt"])
        spring_ready = self.stage("maven", self.maven)
        if spring_ready:
            spring_ready = self.command("spring-build", [self.mvn, "-B", "-ntp", "-f", "examples/spring-config/pom.xml", "package"])
        gradle = [self.bash, "./gradlew", "--console=plain"]
        shop_ready = self.command("shop-build", [*gradle, "-p", "../examples/demo/monorepo", "installDist"], cwd=VERIFIER)
        self.command("web-tests", [self.node, "--test", "tests/test_web_app.js"])
        if sys.platform == "darwin":
            self.command("macos-launcher", [self.bash, "tests/check_macos_launcher.sh"])
        if python_ready and spring_ready and shop_ready:
            self.python_tests(python)
        else:
            self.blocked("python-tests", "Python dependencies, Spring build, or shop build failed")

        baseline = "-Pbaseline.path=" + (self.output / "jvm-baseline.json").as_posix()
        if self.command("jvm-record", [*gradle, "test", "-Pverify.mode=record", baseline], cwd=VERIFIER):
            self.command("jvm-verify", [*gradle, "test", "--rerun-tasks", "-Pverify.mode=verify", baseline], cwd=VERIFIER)
        else:
            self.blocked("jvm-verify", "JVM baseline recording failed")
        self.command("jvm-worktrees", [self.bash, "src/test/scripts/integration.sh"], cwd=VERIFIER)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="new directory for logs and evidence")
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output = (args.output or ROOT / ".local" / f"full-tests-{stamp}-{uuid4().hex[:6]}").resolve()
    try:
        output.mkdir(parents=True)
    except OSError as error:
        parser.exit(2, f"Could not create a new evidence directory: {error}\n")
    print(f"Evidence directory {output}", file=sys.stderr, flush=True)
    verification = Verification(output)
    exit_code = 1
    try:
        verification.run()
        exit_code = int(any(stage["status"] != "PASS" for stage in verification.stages))
    except KeyboardInterrupt:
        exit_code = 130
    finally:
        report = {"schemaVersion": 1, "verdict": "PASS" if exit_code == 0 else "FAIL", "exitCode": exit_code,
                  "stages": verification.stages, "report": str(output / "report.json")}
        evidence = output / "shop-suite/report.json"
        if evidence.is_file():
            report["shopSuite"] = evidence.relative_to(output).as_posix()
        content = json.dumps(report, indent=2) + "\n"
        (output / "report.json").write_text(content, encoding="utf-8")
        print(content, end="")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
