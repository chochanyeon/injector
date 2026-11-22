# Monorepo registration protocol v0.1

**English** · [한국어](registration-protocol.ko.md)

Use this artifact contract for discovery and review. The reviewed runtime registry follows its own schema. For requested runtime edits, follow the [runtime registry guide](runtime-registry-guide.md).

## Inputs and scope

Confirm the monorepo path, target app or candidate list, profile, and mode. If the profile is open, keep the candidate configurations separate. For repository-wide onboarding, inventory runnable apps and investigate them one at a time.

Use `rg --files` for build definitions, Compose, Dockerfiles, scripts, IntelliJ run configurations, and app configuration. Exclude build outputs, dependencies, and large data unless needed for evidence.

| Area | What to verify |
|---|---|
| Maven, Gradle, and other builds | Module structure and runnable apps versus libraries |
| Scripts and IDE | Main entry point, working directory, JVM flags, environment, and profiles |
| Config and client source | Outbound addresses, database and broker connections, references, and defaults |
| Compose and Dockerfiles | Service names, internal and published ports, commands, and health checks |
| Mocks | WireMock coverage and the mocks' own dependencies |
| Vault config and client | Whether the app reads files or environment variables or calls Vault; API version, mount, paths, response keys, and auth requests |
| Docs and samples | Intended behavior and differences from actual launch settings |

A JAR dependency alone supplies little evidence of a runtime edge. Shared hostnames alone provide insufficient evidence of service identity. For a common broker, record the broker first and check producer and consumer startup against the scenario.

## Values and evidence

- Separate observed values, local proposals, and unknowns. Preserve existing settings while investigating.
- Trace environment references, profile overlays, and config server inputs. Use `null` and a finding for unconfirmed values.
- Record secret reference names and omit credential values from artifacts and excerpts.
- Cite source-relative paths and line numbers. Use `observed` for direct evidence, `inferred` for conclusions, and `proposed` for a change proposal.
- Distinguish name resolution, bind addresses, logical hostnames, service names, and container versus published ports. Record protocols, paths, TLS, and auth requirements.
- Use `null` for unknown readiness paths and ports.

## Deliverables

By default, write `registration-draft.json` and `findings.md` under Injector's `registries/<repo-id>/onboarding/`. Keep the repo ID stable across worktrees and respect a user-selected output path. Read existing files before updating. Runtime reads the separate `registry.json`.

### Draft JSON

Use the [example](../assets/registration-draft.example.json). Put extra observations in findings and record the reason if the draft contract changes.

| Field | Meaning |
|---|---|
| `draftVersion` | `0.1` |
| `status` | `draft` |
| `scope` | App IDs and profile or mode, or `null` |
| `nodes` | App, infrastructure, mock, and external registration candidates |
| `nodes[].id` | Stable unique ID |
| `nodes[].kind` | `application`, `infrastructure`, `mock`, or `external` |
| `nodes[].repoPath` | Repo-relative path or `null` for external resources |
| `nodes[].execution` | `mode`, `workingDirectory`, `command` argument array, `mainClass`, `vmOptions`, and `environment`; unknown fields are `null` |
| `nodes[].endpoints` | Named endpoints |
| `endpoints[].id` | Unique within the node |
| `endpoints[].protocol` | Verified protocol |
| `endpoints[].bind` | Listening `host` and `port` |
| `endpoints[].addresses` | Caller-specific `from`, `host`, `port`, `scheme`, and `path` |
| `nodes[].readiness` | Verified readiness check or `null` |
| `dependencies` | Directed edges with `from`, `to`, `endpoint`, and `injections` |
| `injections[]` | `channel` (`environment` or `vmProperty`), `key`, and structured `source` with node, endpoint, and caller |
| `nameMappings` | Observed or proposed `hostname`, `address`, and `mechanism` |
| `evidence` | JSON Pointer `field`, `status`, `locations` with `path` and `line`, and `note` |
| `findings` | Unknown, conflict, or blocker with `id`, `severity`, `field`, `message`, and `question` |
| `startupOrder` | DFS postorder for the selected graph, or `null` |

Record commands as argument arrays for review. Use structured sources and keep shared settings distinct from profile-specific results. Use an empty array for confirmed absence. Use `null` and a finding for uninvestigated or unconfirmed values.

### Findings

Document scope, exclusions, app inventory and evidence, selected graph, existing endpoints, local proposals, conflicts, questions, and next actions. Mark readiness and launch unknowns as blockers where relevant even when an order can be calculated.

Record the dependency search scopes and any custom rules, then keep the remaining candidates and the first follow-up in findings. A resumed investigation can start from those candidates and repeat the search for changed source or launch settings.

## Review the graph

1. Draw edges from caller to dependency. Trace prerequisites recursively.
2. Apply the selected profile and real or mock variant. Follow the mock's own dependencies.
3. Use one ID per shared resource and record incompatible ports or definitions as conflicts.
4. Report a cycle path when revisiting an active node. Leave `startupOrder` as `null` for cycles or unresolved edges.
5. Calculate DFS postorder using dependency order, with shared nodes included once.

## Vault mock discovery

When the user requests local values, investigate the needed API and use local values. Direct clients may use WireMock. Apps reading only the environment or files may use their existing inputs.

For local mocks, split secret paths and fixture values by service ID. The convention is `/v1/<mount>/data/<service-id>`. Keep values separated even when key names match. Verify where the app can configure the path and ask if that remains unclear.

Record method, path, KV version, mount, header names, envelope, read keys, and the configuration key for the address. Mark missing local values as unresolved. Verify KV version before choosing `data.data`. Confirm any login, lookup, renewal, namespace, or engine discovery request from client evidence. Identify unsupported requests and keep company tokens and passwords out of artifacts. Put detailed observations in findings.

## Completion checks

- JSON parses and node, endpoint, dependency, and injection IDs are consistent.
- Each material value and edge has evidence, a proposal, or an explicit unknown.
- Files and lines were verified and secrets omitted.
- Modes, profiles, and caller contexts remain separate. Sharing and cycles were checked.
- Dependencies precede callers in `startupOrder`, or the unresolved order is `null`.
- Report only actions actually performed, including hosts changes, settings application, and app startup.

Group questions by the blockers that affect the plan, such as app selection, profiles, dependency identity, ports, and host conflicts. Continue independent discovery while waiting.

## Convert a reviewed draft

```text
python injector.py draft-check <registration-draft.json>
python injector.py draft-convert <registration-draft.json> --project <source-worktree> --output <new-candidate.json>
```

Conversion handles one reviewed profile and its reachable nodes. Use the full readiness shape from the runtime schema. Supply `projectPath`, `module`, and `mainClass` for IntelliJ, `workingDirectory` and `command` for a process, or `file`, `service`, and `projectName` for Compose. Add the runtime `component` (`url`, `host`, or `port`) to every injection source. Execution settings for the reviewed launch may include `environment`, `vmOptions`, `vmProperties`, and `springProperties`. Omit unused channels. Leave unconfirmed inputs unresolved and keep their findings until reviewed.

Add evidence for every in-scope node and edge, check source-relative locations, and supply the expected `startupOrder`. The converter writes a new runtime registry using variant `local` for each reviewed node. Keep evidence in the draft. Review the candidate alongside existing files before applying changes.
