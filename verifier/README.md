# Verifier

**English** · [한국어](README.ko.md) · [Injector](../README.md)

Verifier compares an application's behavior before and after a dependency upgrade. The Gradle verifier runs on Java 17+ and supports Spring Boot 3.x, Spring MVC, and Jackson 2. It profiles the application classpath, Spring beans and MVC mappings, DTO serialization, selected JSON GET responses, and user-defined probes.

Use `python injector.py compare-http <baseline.json> --candidate <current.json>` from the repository root for two Injector HTTP recordings. Use `compare-worktrees` to record and compare one scenario across two existing checkouts in a single command. [HTTP observation demo](../examples/demo/http-observation/README.md)

Both commands also compare version 2 HTTP and Kafka traces collected through Loki. [Shop checkout trace](../examples/demo/monorepo/README.md#compare-a-checkout-trace)

## Verify a local bug fix

Write a reviewed version 2 scenario with `expect` for the main response and `stateChecks` for read-only GET requests to endpoints in the selected dependency graph. A `before` check protects the starting state. An `after` check can use `timeoutSeconds` to wait for an asynchronous result. Declare only fields safe to keep in the evidence files.

- Run `compare-worktrees` for normal parity. Each checkout must satisfy the declared behavior. The recorded behavior must match.
- Add `--prove-fix CHECK_ID` to require a confirmed failure on the baseline and a complete, passing candidate. Use `response`, the ID of an `after` check, or an event count check ID. You can use the same flag with `compare-http` to verify existing recordings.
- Open `report.json` in the worktree comparison output folder. It contains the verdict, startup events, and available recordings. An incorrectly prepared fixture or unavailable observation can yield `INCONCLUSIVE`.

[Shop checkout fix](../examples/demo/monorepo/README.md#verify-a-checkout-fix)

Use `trace.eventCounts` to require an exact count of events matching a service, event type, and dependency where applicable. Each rule has an `id`, `match`, and `count`. Set `trace.settleSeconds` to the time during which the observed trace must remain unchanged. Verifier counts after the required events are present and this window completes. A count of zero applies to the observed request and window. A missing or unstable trace yields `INCONCLUSIVE`.

## Run a suite

Use `verify-suite` to run reviewed scenarios for one target and profile. A version 1 suite lists its `target`, `profile`, and `cases`. Each case points to a scenario file relative to the suite file. Use `proveFix` for a case that must reproduce a named failure on the baseline. Other cases check parity. Declare each scenario once.

Use `check-suite` with the same suite and checkout paths to inspect launch conditions without creating a session or an output folder.

```text
python injector.py check-suite suite.json --project path/to/baseline --candidate-project path/to/candidate
```

The JSON result has `phase: preflight`, a status of `READY` or `BLOCKED`, and exit code 0 or 2. It lists the resolved registry, selected variants, and startup order for each worktree, plus the declared cases. Diagnostic codes identify the affected `side`, `case`, or `node` when known. `missing_environment` includes the variable name, and `port_in_use` includes the port. Resolved setting values are excluded. `READY` means the declared launch checks passed at inspection time. The actual run checks again when it takes the runtime lock.

```text
python injector.py verify-suite examples/demo/monorepo/scenarios/checkout-fix-suite.json --project path/to/baseline --candidate-project path/to/candidate --output .local/checkout-suite
```

The command uses the same preflight and returns its JSON diagnostic report when execution is blocked. For execution, it starts a fresh session per checkout and case. Use temporary storage or verify the initial state for dependencies that retain data. A completed difference does not stop later cases. A runtime failure stops the suite and marks pending cases `NOT_RUN`. The overall verdict is `FAIL` when any case confirms a failure. It is `INCONCLUSIVE` when evidence is incomplete and no case confirms a failure.

Open `summary.md` for review or `report.json` for automation. Each case links to its paired report and the available recordings. Use the same optional `--registry` as for `compare-worktrees`.

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
