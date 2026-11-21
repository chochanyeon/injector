# Verifier

**English** · [한국어](README.ko.md) · [Injector](../README.md)

Verifier compares an application's behavior before and after a dependency upgrade. The Gradle verifier runs on Java 17+ and supports Spring Boot 3.x, Spring MVC, and Jackson 2. It profiles the application classpath, Spring beans and MVC mappings, DTO serialization, selected JSON GET responses, and user-defined probes.

Use `python injector.py compare-http <baseline.json> --candidate <current.json>` from the repository root for two Injector HTTP recordings. Use `compare-worktrees` to record and compare one scenario across two existing checkouts in a single command. [HTTP observation demo](../examples/demo/http-observation/README.md)

## Verify an application

```bash
bash /path/to/injector/verifier/verify-upgrade.sh --repo /path/to/service -- \
  -Pverify.application=com.example.Application \
  -Pverify.profiles=upgrade-verification \
  '-Pverify.get.paths=/api/products/7,/api/products?page=0'
```

For a Gradle monorepo, add `--project :services:catalog` before `--`. The target needs a committed HEAD and a Gradle wrapper. Run the script from Bash on macOS or Linux, or Git Bash on Windows.

The script creates a temporary detached worktree for HEAD and runs the same verifier snapshot on that baseline and the current checkout. Both executions use the target's Gradle wrapper and application dependencies. Standard output is one line, `PASS` (exit 0) or `FAIL` (exit 1). Gradle logs and diagnostics go to stderr. A PASS applies to the configured requests, DTO samples, and probes.

### Configuration

| Property | Purpose |
| --- | --- |
| `verify.application`, `verify.profiles` | Select the Spring Boot application and active profiles. |
| `verify.get.paths` | Select HTTP JSON GET paths alongside `/actuator/health`. |
| `verify.dto.classes`, `verify.dto.samples` | Add DTO types and source their sample JSON. |
| `verify.scan.packages` | Set the packages inspected for DTO consumers. |
| `verify.ignore.json.pointers` | Exclude specific nondeterministic JSON values. |
| `verify.alignment.groups` | Enforce version alignment in selected dependency groups. |
| `verify.probe.classes` | Compare fingerprints returned by registered `RuntimeProbe` implementations. |

The test reports show where a JSON fingerprint differs. Object key order is ignored. Array order, field presence, and numeric values are compared. Exclusions refer to the original array indexes. Keep the application fixtures and profiles deterministic in both checkouts. The [detailed Korean guide](README.ko.md) documents the comparison rules and manual Gradle execution.

## Verify this module

Run these from `verifier/`. Use `gradlew.bat` on Windows or `./gradlew` on macOS and Linux.

```bash
./gradlew test --tests '*VerifierMechanicsTest'
./gradlew test --tests '*UpgradeConsistencyVerifierTest' -Pverify.mode=record -Pbaseline.path="$PWD/baseline.json"
./gradlew test --tests '*UpgradeConsistencyVerifierTest' --rerun-tasks -Pverify.mode=verify -Pbaseline.path="$PWD/baseline.json"
bash src/test/scripts/integration.sh
```
