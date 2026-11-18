# Shared design for local development environments

**English** · [한국어](design.ko.md)

- Status: requirements draft with a minimal POC requested by the user
- Initial date: November 16, 2026
- Stage: design and POC in parallel. The product stack remains open.

This document provides shared requirements and architectural background. Start with the [work index](index.md) for item-specific design, development, verification, and resume notes. The [project status](status.md) tracks current implementation.

## 1. Problem and goals

Running a project can require coordinated JVM options, environment variables, external applications, databases, Kafka, and Redis. When these are tightly coupled, reproducing an environment becomes difficult and local development inherits problems from a shared development environment.

Manage settings and dependencies as one execution configuration. A developer should be able to run and debug the main app in IntelliJ while choosing how to prepare each dependency. The model should accommodate all mocks, all real dependencies, and a mixture. Initial support for each option can be decided separately.

## 2. Requirements status

| Status | Meaning |
|---|---|
| Confirmed | A requirement confirmed by the user |
| Proposed | An option for review |
| Open | A decision that needs more information |

The structure and behavior in this document are proposals unless marked otherwise. Confirmed requirements are tracked separately from technology choices, implementation scope, and priorities.

## 3. Confirmed requirements

| ID | Requirement | Acceptance evidence |
|---|---|---|
| R-01 | Manage and inject complex JVM options and environment variables. | The selected configuration reaches the target app. |
| R-02 | Support running and debugging the main app in IntelliJ. | A developer can set a breakpoint and inspect execution. |
| R-03 | Provide a Docker execution path. | The Docker path can be used independently of IntelliJ. |
| R-04 | Run required infrastructure such as databases, Kafka, and Redis. | Selected services start and app connectivity can be checked. Product and version support is tracked separately. |
| R-05 | Use WireMock to support local execution independently of shared development services. | Selected API calls reach the local mock. |
| R-06 | Model real and mocked dependencies. | The model can express all-real, all-mock, and mixed configurations. |
| R-07 | Establish the design documentation, then build a minimal POC when requested. | Requirements and open decisions remain visible alongside POC results. |
| R-08 | Manage endpoints and dependencies for each app. | The model represents names, bind addresses, ports, caller-specific addresses, and injection points. |
| R-09 | Traverse transitive dependencies with DFS and start prerequisites first. | Each dependency's own dependencies become ready before it starts. |
| R-10 | Prepare and inject the environment before starting the target. | Each app receives its settings before startup. Automatic IDE integration remains open. |
| R-11 | Provide a skill or protocol for LLM-assisted monorepo onboarding. | An LLM can document runnable apps, endpoints, and transitive dependencies with evidence and produce a reviewed draft. |
| R-12 | Substitute Vault-style configuration reads with a local API and local values. | Match the requested path, response shape, and keys without requiring a real Vault instance. See T-130. |
| R-13 | Give Vault mock values service-specific paths. | The same mock origin returns service-specific values for identical keys. Each app receives its own path. See T-131. |
| R-14 | Generate Spring YAML and JVM-only configuration and guide AI registry maintenance. | Preserve source YAML, inject an additional location, and use repository evidence to determine each setting's profile, source, and channel. Use the actual schema and validation CLI. See T-140. |

## 4. Terminology

| Term | Definition |
|---|---|
| Target project | The project whose local execution environment Injector manages |
| Main application | The app the developer currently intends to run or debug |
| Dependency | An API, app, or infrastructure service required by an app or another dependency |
| Execution configuration | The settings, dependency choices, and main app execution method |
| Execution session | One preparation and use of an execution configuration |
| Mock | A substitute that supplies the needed behavior |
| Real local execution | A dependency app or infrastructure service running locally |
| External connection | A connection to an existing shared or external service. Support was open in the initial design. |

## 5. Responsibilities

Candidate responsibilities include resolving and validating settings, preparing dependencies, resolving connection addresses, integrating with IntelliJ, reporting status, and cleaning up sessions.

The final product packaging remains open. The POC CLI generates configuration and prepares dependencies. The developer starts Debug in IntelliJ without a dedicated plugin. Section 14 records the original workflow.

Choose mocks by dependency type and protocol. WireMock covers HTTP behavior. Whether and how to mock database, Kafka, and Redis behavior requires a separate decision.

## 6. Dependency model

Choose how to satisfy each dependency independently of the main app's IntelliJ or Docker execution method.

| Method | Meaning | Initial decision |
|---|---|---|
| Mock | Supply a defined response or behavior through a substitute | Direction confirmed. Specific coverage remains open. |
| Real local service | Run the app or infrastructure locally | Direction confirmed. Runner and ownership details remain open. |
| External service | Connect to an existing resource specified by the user | Support under consideration. |

The model records relationships between dependencies. If the main app uses Orders and Orders uses a database, running real Orders can require the database. Whether the database is still needed with mock Orders depends on the other selected edges.

The model uses a directed graph because several apps can share a dependency. Traverse from the target using DFS and prepare dependencies first. Section 15 describes the planning rules.

## 7. Scenarios

### S-01. Debug the main app with mocked external APIs

1. The developer selects the target project and configuration.
2. Injector prepares the selected mocks and infrastructure.
3. Injector applies JVM options and environment variables, including local addresses.
4. The developer debugs the main app in IntelliJ.

Verify that selected API calls reach their mocks and that IntelliJ debugging works.

### S-02. Debug the main app with real dependency applications

1. Select a configuration that runs real dependency apps locally.
2. Identify and prepare their prerequisites.
3. Apply the real local connection addresses to the main app.
4. Debug the main app in IntelliJ.

Verify communication with real apps and readiness of their prerequisites.

### S-03. Mix real services and mocks

Run real applications and infrastructure alongside selected API mocks. Verify that the effective settings and connection addresses agree with each choice.

### S-04. Run the main app in Docker

Start the main app and surrounding environment through Docker. Use the same execution configuration model as the IntelliJ path. Define address translation for container callers separately.

## 8. Configuration injection

| Area | Design question |
|---|---|
| Inputs | Where to read existing JVM options and environment variables and how to represent them |
| Merge | Which common, project, personal, and execution-specific layers to support and in what order |
| Conflicts | How to report duplicate keys and interactions between JVM properties and environment variables |
| Substitution | Where to inject runtime addresses, ports, and similar values |
| Provenance | How to trace each effective value to its source |
| Secrets | Where to store values, what to exclude from sharing, and how to redact the UI and logs |
| IntelliJ | Whether to generate, edit, or inject a run configuration |

Treat application framework precedence and Injector's merge rules separately. Define overwrite and restoration behavior before editing existing IntelliJ configurations.

## 9. Sessions and resource management

Proposed flow: select configuration → validate → inspect plan → prepare dependencies → check readiness → run or debug the main app → stop and clean up. Whether reviewing the plan requires an explicit approval remains open.

Follow-on design should specify:

- How to distinguish process startup from service readiness
- Dependency order, cycles, and port conflicts
- Which steps to stop, retry, or clean up after partial failure
- How to distinguish Injector-managed resources from existing resources
- Whether multiple projects or sessions can share infrastructure
- What happens to resources when an app, IntelliJ, or Injector exits
- Retention and reset for database data, Kafka messages, and Redis data
- Initialization scope for schemas, sample data, and topics

Infrastructure initialization is a candidate feature.

## 10. Local isolation

1. Functional independence prepares dependencies locally so the app can run without the shared development environment.
2. Network restrictions technically prevent unintended outbound connections as well.

The confirmed direction is functional independence. Enforcing network restrictions remains open. Address substitution alone provides no network enforcement.

## 11. Open decisions

| ID | Decision | Information needed |
|---|---|---|
| D-01 | Product packaging and IntelliJ integration | Desired workflow, installation constraints, and how existing configurations are used |
| D-02 | First supported project types | Languages, frameworks, build tools, and project layout |
| D-03 | How to import existing settings | Where JVM options and environment variables are managed and representative complexity |
| D-04 | Mock scope | API protocols and state, authentication, or asynchronous behavior to match |
| D-05 | Real dependency runners | Whether to support source, built artifacts, containers, or a combination |
| D-06 | Infrastructure coverage and initialization | Products, versions, initial state, and retention needs |
| D-07 | Settings storage, sharing, and secrets | Personal or team use and repository constraints |
| D-08 | Isolation and external connections | Permitted outbound services and any network-enforcement requirements |
| D-09 | Initial scope and priorities | The smallest scenario to verify on a representative project |

## 12. Design sequence and acceptance criteria

1. Collect actual startup procedures and settings from a representative project. Verify that inputs and dependencies are understood.
2. Detail the execution and dependency model. Verify that it expresses S-01 through S-04 independently of technology choices.
3. Decide IntelliJ integration and resource ownership. Verify responsibilities for normal runs, partial failures, retries, and shutdown.
4. Agree on the initial implementation scope and check each requirement against its acceptance criteria.

The minimal sample-project POC followed a user request to start implementation. Product scope and integration with existing projects remain separate decisions. See the [README](../README.md) for the current workflow.

## 13. Decision records

For each decision, record the D-ID, background, options, outcome, rationale, constraints, and related R-IDs. When changing a decision, record why it supersedes the earlier one.

The next sections preserve POC decisions for IntelliJ, Docker, WireMock, and infrastructure startup. Check the [project status](status.md) for later implementation.

## 14. POC configuration and IntelliJ integration

### 14.1. Choice and scope

- Decisions D-01, D-03, and D-07. Requirements R-01 and R-02.
- Use a Python CLI to read source settings and generate an IntelliJ Application run configuration in XML.
- Validate JVM injection and debugging without requiring an IDE plugin.
- The initial scope was the sample Maven/JVM project. Product packaging, import, and team secret sharing remained open.

Injector code, tests, and docs live at the repository root. The Java target is a separate Maven project under `examples/demo/` with its own source, `pom.xml`, configuration, and Docker files.

### 14.2. Source and generated configuration

The legacy source of truth is `examples/demo/config/project.json`. It defines the IntelliJ module, main class, and shared and per-profile JVM options and environment variables.

```text
examples/demo/config/project.json + selected profile (mock or real)
  → Merge shared and profile settings
  → Generate examples/demo/.run/Injector-<profile>.run.xml
  → IntelliJ discovers the configuration
  → Developer starts Run or Debug
  → JVM receives options and environment variables at startup
```

Profile environment values override shared settings. The legacy JVM option arrays are concatenated in shared-then-profile order. Duplicate `-D` keys are left in the option list. For example, shared `-Xmx256m` and `-Dfile.encoding=UTF-8` plus mock `-Dinjector.profile=mock` populate the XML's `VM_PARAMETERS`. Environment variables go in the XML's `envs` elements.

View the generated values under Run → Edit Configurations. The app reads `injector.profile` with `System.getProperty` and `DEMO_MESSAGE` with `System.getenv`. The settings apply when starting a new JVM.

### 14.3. Project-scoped configuration and sharing

The demo generates `Injector-mock` and `Injector-real` in `examples/demo/.run/`. Open `examples/demo/pom.xml` separately to use them. The repository shares source configuration and generation code. Generated XML, Docker settings under `.local/`, and Java build outputs stay out of Git. Keep real credentials out of source settings.

Regeneration overwrites the corresponding generated configuration. Make persistent changes in the source. Other IntelliJ configurations are outside the generator's scope. The original proposal for work projects was to specify the path, module, and main class and generate a project configuration. Later centralized storage is tracked in [T-200](work-items/T-200.md).

### 14.4. Commands and verification

| Command or operation | Responsibility |
|---|---|
| `python injector.py generate --profile mock` | Generate IntelliJ and Docker settings without starting the environment. |
| `python injector.py up --profile mock` | Generate settings and prepare selected dependencies. Start the main app in IntelliJ. |
| IntelliJ `Injector-mock` Debug | Launch the main JVM with the generated configuration and attach the debugger. |
| `python injector.py run --profile mock` | Pass the same resolved settings to Java as command arguments and process environment variables. |
| `python injector.py up --profile mock --main-docker` | Apply the same settings and container-side addresses to the Dockerized app. |

The original check verified both profiles with IntelliJ IDEA 2025.3.3 and JDK 21, including breakpoint pause and resume, VM options, and environment variables. Both API variants also worked in Docker. [README](../README.md) · [Verification history](validation-history.md)

## 15. Application registry and recursive execution

### 15.1. Applications and endpoints

The central model captures apps and infrastructure, endpoints, and dependencies. Injection and process or container startup apply that model. The original file format was open. The model needs the following fields.

| Field | Example or purpose |
|---|---|
| ID | Identify Orders, Payments, or the Orders database in the graph. |
| Execution | IntelliJ, local process, or Docker plus the required project information. |
| Endpoint | Distinguish business APIs, management APIs, and debug ports. |
| Bind | The listening address and port. |
| Logical hostname | A name such as `payment.local.test.com`. |
| Name resolution | Map the logical hostname to an address such as `127.0.0.1`. |
| Caller address | Protocol, host, and port for a host JVM or container caller. |
| Dependency | The required endpoint and real or mock choice. |
| Injection | The environment variable or JVM property receiving the endpoint. |
| Readiness | How to decide that the next app can start. |

macOS and Windows support previewing, applying, and removing project-owned hosts entries. Prepare checks name resolution for selected host endpoints. External DNS and in-container names are managed by their environments. [T-160](work-items/T-160.md)

### 15.2. DFS execution order

Use the target as the root. Visit dependencies recursively and run each node in postorder. Process sibling dependencies in order. Parallel execution is outside the current scope.

```text
Target app A
├── App B
│   └── DB D
└── App C
    ├── DB D (shared)
    └── Redis E

Example order: D → B → E → C → A
```

For each node, wait for prerequisites, inject the addresses and JVM or environment settings, start the app, and check readiness. Apply the same preparation to an IntelliJ target while leaving the developer in control of Debug.

The registry plan computes DFS order. T-050 and T-060 connect the plan to startup. Automatic IDE initialization before Run or Debug remains a follow-on. The developer currently starts Debug.

### 15.3. Proposed plan and failure rules

- Validate the reachable graph and calculate its order before launching resources. Report missing nodes and cycles.
- Track in-progress and completed DFS visits and report cycles such as `A → B → A`. Handling cyclic startup requires further design.
- Prepare a shared dependency once per plan. Flag incompatible requirements on the same ID.
- Follow the selected mock's dependencies when substituting for a real app. A database used only by the real variant drops out unless another selected path still requires it.
- Block dependents when a prerequisite fails to start or become ready. Define retry and cleanup separately.
- Decide when an existing resource can be reused and how its identity and configuration are verified. An open port alone is insufficient evidence.

Verify multilevel order, shared resource deduplication, cycle reporting, failure propagation, and variant-specific traversal. See D-01 for automatic IntelliJ startup.

## 16. LLM-assisted monorepo onboarding

Use the [skill](../skills/injector-register-monorepo/SKILL.md) and [draft protocol](../skills/injector-register-monorepo/references/registration-protocol.md) to investigate an existing monorepo. Any LLM that can read the protocol can use it. Automatic analysis and import are separate work.

Inputs are the monorepo path, target, profile, and mode. Extract IDs, entry points, JVM options, environment variables, endpoints, hostnames, runtime edges, and readiness from source and execution definitions. Trace transitive dependencies and record build references separately.

Produce reviewed JSON and findings with file and line evidence, inferences, local proposals, and unknowns. Confirm hosts and ports from evidence and omit raw credentials. Report sharing, cycles, port conflicts, and profile differences.

Protocol v0.1 defines a draft. Runtime settings remain a separate contract. Conversion, application, name resolution, and startup are follow-on work.

## 17. Local prepare command and browser UI (T-050, T-060, T-150)

`prepare app-id --project directory --profile name` connects DFS, configuration preflight, dependency startup, and readiness checks. For IntelliJ targets, the developer starts Debug with the generated configuration. `dummy` and `real` are profile aliases. Details and limits follow the work items.

A loopback Python HTTP server exposes the same prepare and stop operations as the CLI. `Start-Injector.command` on macOS and `Start-Injector.vbs` on Windows open the browser. The UI selects a project, profile, and app and shows order, progress, failures, and the Debug entry point. [Registry editor](work-items/T-170.md)

The initial policy uses one session per project. Reprepare replaces the previous managed resources. Conflicting services are reported. Failure cleans up the resources started by that session in reverse order. Process creation times and Docker labels identify ownership. Volumes, networks, and apps started from the IDE remain under their existing ownership. See T-090 for expanded resource sharing and recovery.
