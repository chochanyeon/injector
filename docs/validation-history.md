# POC verification history

**English** · [한국어](validation-history.ko.md)

[Work index](index.md) · [Demo POC](work-items/T-000.md) · [Registration support](work-items/T-005.md)

This page records the environment and procedures from earlier checks. Each work item contains its later results. The original verification was on November 16, 2026. After it, the demo moved to `examples/demo/`. Run commands from the Injector root and open `examples/demo/pom.xml` as a separate IntelliJ project. Java paths below are relative to the demo.

## Environment

- Windows with Docker Desktop's Linux engine
- IntelliJ IDEA 2025.3.3 and Microsoft JDK 21.0.10
- CLI compilation with JDK 25.0.3 and `--release 17`
- Docker apps using Eclipse Temurin JDK and JRE 17
- Python 3.14.4, Docker 29.4.0, and Compose 5.1.1

## Results

| Runner | Profile | Dependency address | Result |
|---|---|---|---|
| IntelliJ Debug | mock | `http://localhost:18081` | WireMock response, breakpoint pause and resume |
| IntelliJ Debug | real | `http://localhost:18082` | Catalog response, breakpoint pause and resume |
| Docker | mock | `http://wiremock:8080` | HTTP call from the main app |
| Docker | real | `http://catalog:18082` | HTTP call from the main app |

Assertions checked that `/demo` returned the selected `profile`, and that its `message` matched the environment value `environment injected`. The parsed `downstream` JSON had `source` equal to `wiremock` or `real`. Docker runs also checked `catalogUrl` against the internal address.

## IntelliJ procedure

1. Prepare dependencies with `python injector.py up --profile mock --infra postgres redis kafka`.
2. Confirm that IntelliJ detects `Injector-mock` after Maven import.
3. Set a breakpoint at `Main.java:31` and start Debug.
4. Call `/demo` and confirm a pause in `lambda$main$0`.
5. Check `catalogUrl`, the request URL, and response status `200` in the debugger.
6. Resume with F9 and check settings and response from the client.
7. End the session, prepare the real dependencies, and repeat with `Injector-real`.

Both runs connected IntelliJ directly to the main JVM via JDWP.

## Docker procedure

Stop the IntelliJ app and run the commands in order, checking `/demo` after each.

```powershell
python injector.py up --profile mock --main-docker
python injector.py up --profile real --main-docker
```

Both common and profile settings reached the Docker main app, and host addresses were translated to Compose addresses. The Docker main app was stopped after verification.

## Infrastructure and settings

- PostgreSQL ran `select 1` in the `demo` database.
- `redis-cli ping` returned `PONG`.
- Kafka created `injector-poc` with one partition and replication factor one.
- WireMock returned the `/product` mapping.
- Healthchecks passed for the four infrastructure and mock containers.
- `python -m unittest discover -s tests -v` passed two configuration tests.

The `up` completion message was corrected to direct users to start Debug when only the dependencies were prepared.

## Scope

The sample verified injection, switching downstream variants, IntelliJ debugging, and Docker execution. Automatic onboarding of work projects, direct use of DB, Kafka, and Redis from the sample app, host client connections, and retention policies required separate verification.

## Checks after moving the demo

After moving source, Maven files, settings, and Docker to `examples/demo/`, both configuration tests and Java 17 compilation passed. Both profile XML files appeared under `examples/demo/.run/`. Compose validation, Docker build from the new paths, and mock and real calls and injection in local Java and Docker all passed. Generated files, builds, and IDE settings were excluded from Git.

The earlier IntelliJ breakpoint evidence predates the move. The moved demo opens as a separate Maven project.

## LLM registration resources

On November 16, 2026, checks covered skill format, example JSON, node and endpoint references, injections, and JSON Pointers to evidence fields. A real work monorepo and automatic conversion were outside that verification.

## Earlier documentation structure

The November 16, 2026 reorganization used numbered 00–04 documents. It checked 38 relative links and index coverage and removed old document name references. The user later chose the [T-ID work index](index.md), which groups design, implementation, and verification per task.

The documentation reorganization reran `python -m unittest discover -s tests -v` and passed two tests. App launch, Docker, and IntelliJ integration procedures were recorded separately.
