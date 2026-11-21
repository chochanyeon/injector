# Injector POC

**English** · [한국어](README.ko.md)

Injector prepares local dependencies and supplies JVM options, environment variables, and Spring configuration for applications you debug in IntelliJ IDEA. Verifier compares recorded local behavior and supports Gradle-based Spring upgrade checks. [Verifier guide](verifier/README.md)

Start with the [work index](docs/index.md) when resuming development. Each work item records its design, implementation, verification, and resume point. The repository root contains Injector itself. The [HTTP observation demo](examples/demo/http-observation/README.md) exercises recording and comparison.

The [shop monorepo demo](examples/demo/monorepo/README.md) exercises six JVM services, shared PostgreSQL and Redis, Kafka delivery, WireMock for pricing and Vault KV v2, and correlated application logs in Loki.

```text
injector/
├── injector.py          # Injector CLI
├── verifier/            # Gradle upgrade checks and observation comparison
├── schemas/             # Registry and HTTP observation contracts
├── tests/               # Injector tests
├── docs/                # Design and verification records
└── examples/demo/       # Example target project
    ├── pom.xml
    ├── src/main/java/poc/
    ├── config/project.json
    ├── docker/
    └── .run/            # Generated IntelliJ configurations (ignored by Git)
```

Run CLI examples from the repository root. Open the demo as a separate project in IntelliJ.

## Prerequisites

- JDK 17 or newer with `java` and `javac` on PATH
- Python 3.10 or newer
- Docker Desktop and Compose. Start Docker Desktop before preparing an environment.
- IntelliJ IDEA. Open `examples/demo/pom.xml` as a Maven project.

On macOS, install the dependencies in a virtual environment at the repository root.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

On Windows, run the following in PowerShell.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Prepare an environment in the browser

- **macOS:** Double-click **`Start-Injector.command`** in Finder. Terminal runs the server and opens the default browser.
- **Windows:** Double-click **`Start-Injector.vbs`** to open the default browser.

Both use `http://127.0.0.1:18770` and reuse a running Injector server. Keep the server's Terminal window open on macOS. If a ZIP download lost the executable bit, run `chmod +x Start-Injector.command` once.

1. Under **Project folder** (**프로젝트 폴더**), choose the source checkout or worktree. Under **Registry file** (**Registry 파일**), use **Choose file** (**파일 선택**) to select any valid Injector registry JSON. The filename and extension are unrestricted. Click **Load** (**불러오기**) after typing either path by hand. A directory path uses the `registry.json` inside it. Leave the field empty to load `registry.json` from the source folder.
2. Select `dummy` or `real` and choose `platform-service`.
3. Review the execution order and click **Prepare environment** (**실행 환경 준비**). Redis starts before Catalog. With `real`, PostgreSQL also starts before Catalog.
4. After preparation, open `examples/demo/pom.xml` and Debug **`Injector-dummy-platform-service`** or **`Injector-real-platform-service`**. Check the response at `http://127.0.0.1:19080/demo`.
5. Stop the app in the IDE. Use **Stop this project's dependencies** (**이 프로젝트의 의존성 종료**) to stop Injector-managed processes and containers. Closing the browser leaves both the server and the dependencies running.

Injector remembers the last successfully loaded project folder and registry file. The next launch preselects and loads them. An explicit `serve --project` takes precedence when starting a new server. Injector stores only the paths in its Git-ignored `.local/web-selection.json`.

Stop the app in the IDE before changing profiles. Preparing again replaces resources from the previous Injector session for that project. Ports in use by other programs and existing Compose services are treated as conflicts. Container volumes and Compose networks are preserved.

Use **Check registry execution requirements** (**Registry 실행 조건 검사**) before preparing to check the selected app, profile, variants, and their dependencies. The result identifies the first blocker in the declared settings or execution definitions. The check leaves services and generated files untouched. Prepare still checks host resolution, port conflicts, and service readiness.

Register each required Compose `depends_on` service in the calling node's dependency graph. For each registered host endpoint, the checker compares its port and transport with the service's fixed publication. With host networking, the host and bind ports must agree. Compose configuration and startup both receive the node's resolved environment. For an IntelliJ target, the check reports the module and main class for confirmation in the imported IDE project.

Selecting the source folder's own `registry.json` explicitly uses the same execution session as leaving the Registry field empty. When a managed process exits before readiness, the error identifies the node and the path to its local diagnostic file when available. The file retains the last 64 KiB of process output and can contain application data. The browser and CLI show its path.

When a Compose file is nested, Injector uses the source-root `.env` as a fallback if the Compose directory has no `.env` and the environment does not override or disable the default. [Docker Compose interpolation](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)

You can also select `support-console`. It uses the same Java main class. Debug `Injector-<profile>-support-console` and check `http://127.0.0.1:19084/demo`. Both demo apps call Catalog. Redis, PostgreSQL, and the Vault mock exercise environment preparation and the dependency graph.

Use the Python executable from your environment. Without activation, substitute `.venv/bin/python` on macOS or `.\.venv\Scripts\python.exe` on Windows. When `--project` is omitted, registry-based prepare looks in the current directory.

```powershell
python injector.py prepare platform-service --project examples/demo --mode dummy
python injector.py prepare platform-service --project examples/demo --mode real
python injector.py plan platform-service --project examples/demo --profile dummy --variant catalog=real
python injector.py prepare platform-service --project examples/demo --profile dummy --variant catalog=real
python injector.py stop --project examples/demo
python injector.py serve --open
```

The **Per-node execution and mock selection** panel (**노드별 실행·대역 선택**) updates the execution order and graph. On the CLI, pass `--variant NODE=VARIANT` once per node. The override applies to the request. A newly required dependency must have an entry in the profile's `selections`. Injector regenerates the IntelliJ configuration under the same app and profile name.

Use `--profile local-dev` for an explicit profile. `--mode dummy` resolves to one of `dummy`, `local-mock`, and `mock`, while `--mode real` resolves to `real` or `local-real`. Use `--profile` if more than one alias exists.

Dependencies can use process, Compose, or external runners. Targets can use IntelliJ, process, or Compose. Process-based JVM injection requires the `java` executable. Generated Spring YAML is available for IntelliJ targets. Compose accepts environment injection, while JVM options belong in the service's own command. An IntelliJ app used as a dependency needs a process or Compose variant for automatic startup. Injector rejects secret values that would be persisted as XML environment variables or VM properties.

## Edit registry files

1. Select the source folder and the registry file and click **Edit registry** (**Registry 편집**). The editor can open existing files with JSON syntax errors. **Change folder** (**폴더 변경**) opens another worktree. For a split registry, choose the root or a node file from **Configuration file** (**설정 파일**). Create new node files in the registry directory and add them to `nodeFiles`.
2. **Validate** (**검증**) checks JSON syntax, schema, references, and cycles in the profile plans. Syntax errors show the line and column.
3. **Save** (**저장**) validates again before writing and refreshes the application and profile lists.

**Collapse** (**접기**) keeps the draft, and reopening the editor for the same selection restores it. **Close** (**닫기**) and Esc ask before discarding unsaved edits. If the file changed on disk, use **Reload file** (**파일 다시 읽기**) to review the newer version.

The native file and folder dialogs open on the desktop running Injector. When using a remote preview, type the path if the host desktop is inaccessible. Restart an existing Injector server after installing an update to use its new API.

## View the dependency graph

The graph shows the applications in the selected profile and the infrastructure they use. Arrows point from each node to its direct dependencies. A shared dependency is shown once.

Choose an app under **Apps to show** (**표시할 앱**) to see its dependencies. Click a node to highlight its direct connections and inspect which nodes it uses and which nodes use it. Click it again to clear the selection. The graph refreshes when the profile changes or the registry is saved. **Direct dependencies** (**직접 의존성 목록**) shows the relationships as text.

Click the graph, execution order, or log heading to toggle that section. Readiness and results stay visible when the execution-order panel is collapsed.

In the demo, **All apps** (**전체 앱**) shows both apps sharing Catalog and the Vault mock. Both `platform-service` and Catalog connect to Redis. The `dummy` profile has five nodes. The `real` profile adds PostgreSQL as a Catalog dependency.

## Use local hostnames

Specify a name such as `catalog.local.test.com` in an endpoint's `addresses.host.host` and register the same name in `nameMappings`.

```json
{"hostname": "catalog.local.test.com", "address": "127.0.0.1", "method": "hosts"}
```

```sh
.venv/bin/python injector.py hosts preview --project examples/registry
sudo .venv/bin/python injector.py hosts apply --project examples/registry
sudo .venv/bin/python injector.py hosts remove --project examples/registry
```

On Windows, use `.\.venv\Scripts\python.exe` and run `apply` and `remove` from an elevated PowerShell. On macOS, run those two commands with `sudo`. Preview works without elevation.

`examples/registry` illustrates the declaration. Use your actual project path for runtime changes. Injector preserves matching manual entries and reports conflicts. `remove` deletes only the entries owned by that project. Run it with the old path before moving the project.

Use `method: external` for an existing OS resolver. Prepare checks that the selected graph's registered names resolve only to the expected IP. Manage hosts changes with the commands above and use Compose service names or `extra_hosts` inside Compose.

## Run the legacy demo

Run the following from the repository root. The first run downloads the container images.

```powershell
python injector.py up --profile mock --infra postgres redis kafka
```

This starts WireMock and the selected infrastructure, waits for readiness, and creates `examples/demo/.run/Injector-mock.run.xml`. Start the main app from IntelliJ.

1. Open `examples/demo/pom.xml` as a separate project and choose JDK 17 or newer.
2. Select `Injector-mock` after Maven import.
3. Set a breakpoint on the `body = ...` line in `src/main/java/poc/Main.java`.
4. Start Debug and call `http://localhost:18080/demo`.

At the breakpoint, inspect the `injector.profile` system property, `DEMO_MESSAGE`, and the API call. The `downstream` field contains the downstream JSON as a string.

To switch to the real sample API, stop the main app, run the following, and Debug the `Injector-real` configuration.

```powershell
python injector.py up --profile real --infra postgres redis kafka
```

The `mock` profile uses WireMock. The `real` profile uses the Java Catalog app. They listen on different ports, so the legacy `up` leaves the previous dependency running when switching profiles.

## Run without an IDE

```powershell
python injector.py run --profile mock
```

Run the matching `up` first. `run` compiles the Java source and runs the main app in the foreground. Stop it with Ctrl+C.

To run the main app in Docker, stop any instance running in IntelliJ or on the CLI first.

```powershell
python injector.py up --profile mock --main-docker
```

## Legacy configuration and commands

The legacy configuration lives at `examples/demo/config/project.json`. Profile values override shared environment variables, and profile VM options follow the shared list.

```powershell
python injector.py plan --profile real --infra redis
python injector.py generate --profile real
python injector.py down
python -m unittest discover -s tests -v
```

`plan` displays environment variable names. `generate` writes the IntelliJ and Docker configurations without starting containers. Git ignores generated files under `.run/Injector-*.run.xml` and `.local/` because they contain runtime settings. The committed database password is a fixed demo value. Keep real credentials out of the repository.

`down` removes the `injector-poc` containers and network. It preserves volumes, but the current anonymous volumes are not guaranteed to reconnect to a subsequent `up`. Data retention and initialization remain open design items.

## Legacy demo ports

| Service | Host address |
|---|---|
| Main app | `localhost:18080/demo` |
| WireMock | `localhost:18081` |
| Catalog | `localhost:18082` |
| PostgreSQL | `localhost:15432`, database and user `demo` |
| Redis | `localhost:16379` |
| Kafka | `localhost:19092` |

Use Compose service names and internal ports between containers. Published ports bind to loopback. Blocking outbound traffic is outside the POC scope.

## Verification and limits

The legacy demo was checked with the following scenarios.

- Configuration merge and generated files with Korean text, XML special characters, and JVM options containing spaces
- Java 17 target compilation with JDK 25
- WireMock mapping responses, PostgreSQL queries, Redis PING, and Kafka topic creation
- IntelliJ IDEA 2025.3.3 with JDK 21, both profiles, and breakpoint pause and resume
- IntelliJ calls to WireMock and the real Catalog with injected JVM options and environment variables
- Dockerized main app calling both downstream variants at their internal addresses

The Java app receives infrastructure settings. Its own code exercises Catalog, while PostgreSQL, Redis, and Kafka were verified separately. The legacy workflow uses fixed profiles and ports for one environment. For current registry-based features such as prepare, session handling, and their limits, see the [work index](docs/index.md) and [project status](docs/status.md). The [design](docs/design.md) records broader decisions, and the [verification history](docs/validation-history.md) records the original procedures. Python, JSON, Compose, and generated IDE files are POC choices.

## Use a local Vault API mock

```powershell
python injector.py up --profile mock --vault-service orders
python injector.py vault-demo --vault-service orders
python injector.py vault-demo --vault-service payments
```

A separate WireMock container serves local values using a Vault KV v2 response. The demo client reads its message and feature flag from that response. The mock uses local authentication data.

The services share an address and port and use names in their paths, such as `/v1/secret/data/orders` and `/v1/secret/data/payments`. They can return different values for the same key in the `data.data` object. [Orders data](examples/demo/docker/vault-mock/__files/orders.json) · [Payments data](examples/demo/docker/vault-mock/__files/payments.json)

`--vault-service` enables the mock and selects a service. With `--with-vault` alone, the default is `orders`. The Java demo receives the Vault URL. A separate Python app exercises the API response. [Vault mock guide](examples/demo/docker/vault-mock/README.md) · [T-131](docs/work-items/T-131.md)

## Validate an application registry

Keep work registry files in Injector's `registries/<repo-id>/registry.json` and place node files in `nodes/` under that directory. Git ignores `registries/`. To reuse the same registry with another worktree, change only the source path.

```text
python injector.py validate --project "<worktree path>" --registry registries/my-monorepo
python injector.py plan platform-service --project "<worktree path>" --registry registries/my-monorepo --profile local
python injector.py prepare platform-service --project "<worktree path>" --registry registries/my-monorepo --profile local
python injector.py stop --project "<worktree path>" --registry registries/my-monorepo
```

The CLI also accepts an explicit file such as `--registry registries/my-monorepo/local-dev.json`. With an external registry, Injector saves generated Spring YAML, IntelliJ XML, Compose overrides, and session files in a directory under `.local/injector/` scoped to the registry file and worktree. Import the generated run configuration into the IDE for that worktree, then start Debug. [IntelliJ run configuration documentation](https://www.jetbrains.com/help/idea/run-debug-configuration.html#share-run-debug-configurations)

### Prepare automatically before IntelliJ Run or Debug

```text
python injector.py ide-tool platform-service --project examples/demo --profile dummy
```

1. Open or import the returned `runConfiguration` in IntelliJ.
2. In **Settings → Tools → External Tools**, create a local tool. Use the returned `program`, `arguments`, and `workingDirectory` for **Program**, **Arguments**, and **Working directory**.
3. In **Run → Edit Configurations**, add the tool to **Before launch → Run External tool** for that configuration. Keep it before the app launch.

The tool waits for preparation and returns a failure exit code if the app should not launch. Repeat launches can reuse a healthy session with the same plan. If the app's injected settings change, generate and import the updated configuration and replace the tool's arguments. Use `stop` to discard the prepared session or recover after a forced termination. [IntelliJ External Tools](https://www.jetbrains.com/help/idea/configuring-third-party-tools.html)

Injector also supports a source-root `registry.json`. Use registry schema 1.1 for Spring YAML settings. For multiple node files, list paths such as `["registry/nodes/platform-service.json", "registry/nodes/catalog.json"]` in `nodeFiles`. Each file contains one node with `id`, `kind`, and `variants`. A variant contains the environment, JVM settings, Spring settings, and injection rules. Put app-specific profile settings in `profileOverrides.<profile>`. The root contains shared defaults and the profile targets and variant selections. Inline `nodes` and root-level `profiles.<profile>.overrides` remain supported.

Resolve `nodeFiles` relative to the selected registry file's directory, and resolve `projectPath`, `workingDirectory`, and Compose paths relative to the source directory. [Demo registry](examples/demo/registry.json) · [Platform service settings](examples/demo/registry/nodes/platform-service.json)

```powershell
python injector.py validate --project examples/registry
python injector.py validate --project examples/registry --profile local-real
```

Omit the profile to check all profiles. `--project` accepts an absolute or relative directory. Validation checks the structure and references, including selected nodes, dependencies, variants, and endpoints. It leaves processes, files, and secret values untouched.

```powershell
python injector.py resolve --project examples/registry --profile local-real --node catalog
```

`resolve` reads the environment variables referenced by `fromEnv` and reports keys and provenance with all values redacted. [T-030](docs/work-items/T-030.md)

```powershell
python injector.py plan --project examples/registry --profile local-real
python injector.py plan --project examples/registry --profile local-mock
```

`plan` shows transitive dependencies in DFS postorder, lists each shared dependency once, and reports a cycle with its path. Planning requires no secret values. The legacy summary remains available with `plan` without `--project`.

The [registry example](examples/registry/README.md) illustrates the model. Use `examples/demo/` for runnable examples. [Schema](docs/work-items/T-010.md) · [Loading and validation](docs/work-items/T-020.md) · [DFS planning](docs/work-items/T-040.md)

## Generate Spring YAML and JVM properties

Use `vmOptions` for JVM flags, `vmProperties` for named `-D` values read by `System.getProperty`, and `springProperties` for Spring YAML values in schema 1.1. Set them in shared defaults, a variant, or a profile override.

```powershell
python injector.py render --project examples/spring-config --profile local --node spring-probe
```

For this IntelliJ example, `render` writes `.local/injector/<profile>/<node>/spring-overrides.yml` and the app's `.run/Injector-<profile>-<node>.run.xml`. The XML combines VM-only settings with `spring.config.additional-location`, which points to the generated YAML. The command leaves the original YAML untouched. Start the app separately.

For values in Spring YAML, `fromEnv` is emitted as `${ENV_NAME}` for Spring to resolve in the app environment. Injector rejects configurations that would write an environment or VM property secret to XML and checks for key conflicts and an existing additional location. [T-140](docs/work-items/T-140.md) · [Spring configuration example](examples/spring-config/README.md)

## Use an LLM for monorepo onboarding

Use the [registration skill](skills/injector-register-monorepo/SKILL.md) and [draft protocol](skills/injector-register-monorepo/references/registration-protocol.md). An LLM without skill support can read the same files.

For a first registration, identify runnable apps, then trace the selected app's infrastructure and application dependencies. For Spring apps, verify which sources actually apply to the selected execution mode. [Monorepo discovery guide](skills/injector-register-monorepo/references/monorepo-initialization.md) · [Spring configuration checklist](skills/injector-register-monorepo/references/spring-configuration-audit.md)

For reviewed runtime changes, trace consumers, profiles, and JVM flags to select the right injection channel. Use `draft-check` to review a discovery draft and `draft-convert` to produce a new candidate from a reviewed profile. Use `validate`, `plan`, `resolve`, and `render` as appropriate. [Runtime registry guide](skills/injector-register-monorepo/references/runtime-registry-guide.md) · [Conversion steps](skills/injector-register-monorepo/references/registration-protocol.md#convert-a-reviewed-draft)

```text
Read skills/injector-register-monorepo/SKILL.md.
Inspect <target app> in <monorepo path> for the local profile.
Record endpoints, transitive dependencies, and injection points with source evidence.
Produce a registration draft and a report of open questions.
```

Drafts and findings go in `registries/<repo-id>/onboarding/`. Put reviewed runtime files in the same repository's registry directory and select the source with `--project`. Injector reads the reviewed `registry.json` at runtime.

## Save verified work

Commit and push each verified work item to `https://github.com/chochanyeon/injector`. Record remaining verification separately.

## References

- [WireMock on Docker](https://wiremock.org/docs/standalone/docker/)
- [IntelliJ Application run configuration](https://www.jetbrains.com/help/idea/run-debug-configuration-java-application.html)
