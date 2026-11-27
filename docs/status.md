# Project status

**English** · [한국어](status.ko.md)

Last updated November 23, 2026. See the [work index](index.md) and individual work items for design and verification details.

## 1. Current stage

The single-demo POC works. The registry supports schemas 1.0 and 1.1, validation of external projects, endpoint resolution, settings merge, DFS postorder planning, and IntelliJ XML and Spring YAML generation. Prepare runs process, Compose, and external dependencies in order. The CLI and loopback web UI share the runtime. Some new IDE, browser, and native picker flows still need direct verification. Python, JSON, and Compose are POC choices.

Develop Injector at the repository root. The Java and Vault demos live at `examples/demo/`, and the Spring probe at `examples/spring-config/`. Run `python injector.py ...` from the root and open the demo Maven project separately in IntelliJ.

## 2. Feature status

| Feature | Status | Behavior and limits | Evidence |
|---|---|---|---|
| JVM and environment merge | Partial | Legacy merge. Registry supports provenance and conflict checks for JVM, environment, and Spring settings. Runner limits are in T-060. | `injector.py:resolve` |
| IntelliJ injection | Implemented for Application configurations | Generates XML and Spring YAML. A configured local External Tool prepares dependencies before Run or Debug. | T-060, T-120 |
| Legacy real or mocked API | Partial | The mock or real profile chooses WireMock or Catalog. | Demo `config/project.json` |
| DB, Kafka, and Redis startup | Partial | Fixed Compose services with healthchecks. The demo app does not use those services directly. | Demo `docker/compose.yaml` |
| Main app | Partial | CLI Java and Docker paths. Developers start IntelliJ Debug. | `injector.py:main` |
| `plan` | Complete for planning | `--project` prints DFS order and dependency metadata. The legacy summary remains available. | T-040 |
| `down` | Partial | Removes containers and networks for the fixed Compose project. Session ownership and recovery are tracked separately. | `injector.py:compose` |
| Vault mock | Complete for demo | WireMock KV v2 read paths with per-service values and a fixed local token. Company Vault and SDK integrations remain unverified. | T-130, T-131 |
| LLM registration | Implemented | A reusable search gathers source locations. The onboarding guide resolves remaining candidates and records evidence before registry review. | T-005, T-140, T-340 |
| Registry schema | Complete | Version 1.0 and the 1.1 Spring extension. | T-010, T-140 |
| Spring YAML and JVM settings | Complete for local rendering | Types and environment placeholders are preserved. IntelliJ uses an additional location. | T-140 |
| Registry loading | Complete for validation | Validates schema, references, and paths. Prepare can use external projects. | T-020 |
| Endpoint and settings resolution | Complete in memory | Resolves caller contexts, merges settings, records provenance, checks conflicts, and handles secret references. | T-030 |
| DFS and shared dependencies | Complete for planning | Postorder traversal, deduplication, and cycle reporting. | T-040 |
| Execution and readiness | Complete for initial scope | Process, Compose, and external runners. HTTP, TCP, and container healthchecks. Owned resources are cleaned up. | T-050 |
| Prepare target | Partially verified | Prepares dependencies and generates Debug configuration. New IDE flow still needs a direct check. | T-060 |
| Browser preparation | Partially verified | Double-click launchers, loopback API, and UI. Manual browser checks remain. | T-150 |
| Registry editor | Partially verified | Opens, validates, and saves files, detects external edits, and uses OS pickers. The macOS picker remains to be verified. | T-170 |
| Per-app files | Implemented | Combines `nodeFiles` and edits individual files in the browser. | T-190 |
| Registry autocomplete | Verified in Windows Chrome | Suggests node file paths, dependencies, injection endpoints, and execution fields. | T-420 |
| Injection rule repair | Verified in Windows Chrome | Validates reachable profiles for key conflicts and edits or removes existing rules in a node draft. | T-440 |
| Central registry storage | Partially verified | Select a registry file separately from the source folder. Shares settings from Injector's `registries/` and isolates runtime state per file and worktree. | T-200 |
| Web selection persistence | Implemented | Normal launches restore the last successfully loaded project and registry paths. | T-240 |
| Registry execution check | Implemented | Browser and CLI check declared settings and runner requirements. Both report the IntelliJ module and main class for IDE confirmation. | T-220, T-230, T-320 |
| Dependency graph | Partially verified | Profile and app filters and direct connection highlighting. Small and large layout checks remain. | T-180 |
| Verifier | Integrated | The original Gradle upgrade verifier runs from `verifier/`. | T-250 |
| HTTP observation | Implemented for one local edge | CLI recording, paired worktree execution, and Verifier comparison with side-by-side results on the dependency graph. | T-260, T-310 |
| Correlated request trace | Implemented for local Loki | Compares HTTP and Kafka events across worktrees and identifies missing required events. | T-330 |
| Local fix verification | Implemented for version 2 scenarios | Checks initial and final state, verifies a named failure and its fix, and saves node startup evidence. | T-350 |
| Worktree verification suite | Implemented for one target and profile | Combines fix and parity checks with fresh sessions and linked JSON and Markdown reports. | T-360 |
| Trace event counts | Implemented for correlated events | Checks expected and forbidden effects within a configured settling window. | T-370 |
| Non-interactive agent workflow | Partially implemented | `check-suite` and `verify-suite` share a read-only preflight with structured diagnostics. The full target-project workflow is open. | T-380 |
| Full test environment | Verified on Windows | A clean checkout passed all 13 stages, including 150 unskipped Python tests, the live shop suite and the JVM verifier. | T-390 |
| Web dashboard | Verified in Windows Chrome | Project selection, execution, the dependency graph, and worktree verification share the local browser workflow. | T-400 |
| Web server shutdown | Implemented | The dashboard exits the local server after confirmation and prevents shutdown during active work. | T-430 |
| Saved verification evidence | Implemented | Reopens project-scoped web runs from disk and shows case verdicts, differences, and recordings. | T-410 |
| Shop monorepo demo | Implemented | Six Gradle JVM modules run with shared infrastructure and replaceable pricing. | T-270 |
| Shop demo Vault and logs | Implemented | All six apps read their own Vault path, including both Pricing variants. One Loki query finds related checkout HTTP and Kafka events by request ID. | T-280, T-290 |
| Execution and comparison review fixes | Implemented | Default registry session identity, Compose port validation, local process diagnostics, selected HTTP query values, and original array indexes for Verifier exclusions. | T-300 |
| Custom hostnames | Partially verified | Preview, apply, remove, and resolution checks on Windows and macOS. Elevated system application remains. | T-070, T-160 |
| macOS and Windows launchers | Partially verified | Finder and VBS launchers with CI on both systems. Direct Finder verification remains. | T-160 |
| Variant overrides | Complete | Request-specific choices apply to the plan, graph, and injection. | T-080 |
| Sessions and recovery | Complete for documented ownership | Checks ports, foreign Compose services, and Docker engine identity. Stops owned resources in reverse order and records cleanup progress. | T-050, T-090 |

`registration-draft.json` is a review artifact. Convert a reviewed profile into a new runtime candidate with `draft-convert`. [T-100](work-items/T-100.md)

## 3. Source map

| Path | Responsibility |
|---|---|
| [injector.py](../injector.py) | CLI, legacy resolution, XML generation, Compose calls, Java execution |
| [tests/test_injector.py](../tests/test_injector.py) | Legacy settings and generation checks plus Vault option and service selection |
| [registry-v1 schema](../schemas/registry-v1.schema.json) | Registry 1.0 |
| [registry-v1.1 schema](../schemas/registry-v1.1.schema.json) | Spring extension |
| [runtime.py](../injector_core/runtime.py) | Prepare, stop, sessions, and readiness |
| [web.py](../injector_core/web.py) | Loopback server and job API |
| [rendering.py](../injector_core/rendering.py) | YAML and IntelliJ XML generation |
| [registry.py](../injector_core/registry.py) | Registry loading and reference validation |
| [tests/test_registry.py](../tests/test_registry.py) | Loader and CLI validation tests |
| [Demo settings](../examples/demo/config/project.json) | Legacy demo configuration |
| [Demo Java sources](../examples/demo/src/main/java/poc/) | Main app and Catalog |
| [Demo Docker files](../examples/demo/docker/) | Compose, Dockerfile, and WireMock mappings |
| [Registration skill](../skills/injector-register-monorepo/) | Tracked skill source |

The installed skill copy lives outside Git. Synchronize changes from the repository and verify the installed copy.

## 4. Verification

- The November 21 Windows review passed all 130 Python tests with Spring Boot and WireMock Vault enabled, plus five browser tests. The temporary Docker and Java smoke test exercised both demo profiles and queried PostgreSQL. See T-090 through T-120 for individual checks.
- Windows passed 113 tests including real Spring Boot and WireMock Vault integration. The Linux runtime check passed 16 tests.
- Actual Docker dependencies were prepared and cleaned up using CLI dummy and real profiles and the web API. Java Main successfully called real Catalog using generated JVM arguments and environment.
- Legacy IntelliJ Debug was verified before moving the demo. Spring XML generation and parsing were verified and real Spring Boot received the equivalent JVM arguments. The new IntelliJ UI path still needs a check.
- Skill checks covered format, links, demo planning, Spring configuration channels, and a scoped first-registration walkthrough with a Gradle path mapping and unresolved configuration. Independent execution and a work monorepo remain pending.

See the [verification history](validation-history.md) for historical environments and procedures. Each work item records its latest evidence.

## 5. Handoff

Both platforms share the local UI. See T-170 for editing and T-180 for the graph. The portable integration fixture verified registration and mixed execution. Verify the same flow with a work monorepo and a real macOS IntelliJ session. [T-110](work-items/T-110.md) · [T-120](work-items/T-120.md)

A fixture can exercise the model while a work monorepo is unavailable. D-01 through D-09 remain in the design. Recheck any running resources at the start of the next session.

## 6. Record the next handoff

Update the work item with deliverables, checks performed, open issues, and the next action. When pausing, record the changed files, failed commands, and reproduction steps. Update this page and the index together.
