# Runtime registry maintenance guide

**English** · [한국어](runtime-registry-guide.ko.md)

Use this guide when asked to write or update a reviewed registry. Use the draft protocol and findings first when required inputs remain unknown. Static checks can follow file edits without launching the application.

## 1. Check the current contract

Distinguish the Injector repository from the target source. Inspect Injector's work index, `schemas/registry-v1.schema.json`, and `schemas/registry-v1.1.schema.json`. Use `examples/registry/registry.json`, `examples/spring-config/registry.json`, and `examples/demo/registry.json` for tested examples. Consult `injector_core/registry.py`, `resolution.py`, and `rendering.py` when behavior depends on implementation.

The default path is Injector's Git-ignored `registries/<repo-id>/registry.json`. Store one app or infrastructure node per file under `nodes/` and list relative paths such as `nodes/catalog.json` in `nodeFiles`. Keep the same registry for other worktrees and change `--project`. Each node contains `id`, `kind`, and `variants`. Existing inline nodes may stay or migrate incrementally. IDs must be unique.

Keep targets and variant selections in `profiles`. Put app values in its variants and `profileOverrides.<profile>`. Existing root `profiles.<profile>.overrides.<node>` is applied last. Compare final values and JVM flag order when migrating. Resolve execution paths and Compose files against the source directory.

Use schema 1.1 when you need Spring YAML fields. Preserve existing IDs, profiles, and user-confirmed values. Record the change reason and evidence in the registry folder's `onboarding/findings.md`.

Set IntelliJ `projectPath` to the directory opened by the IDE. When IntelliJ opens the full monorepo, use its root and distinguish services by module. Confirm per-app project roots from the actual workflow.

## 2. Trace the app's configuration readers

Locate modules and launch definitions with `rg --files`. Choose injection by the consumer.

| Evidence | Registry placement |
|---|---|
| JVM flags such as `-Xmx`, `-XX`, and `-javaagent` | `vmOptions` argument array |
| `System.getProperty` or a wrapper | Named `vmProperties` |
| `System.getenv` or a required variable | `env` |
| Spring Environment, `@Value`, or `@ConfigurationProperties` | Schema 1.1 `springProperties` or the environment expected by a placeholder |
| Direct YAML or properties parsing | Verify the specific input path |
| Vault client | Verify path and response keys, then model a service-specific mock if requested |

Use the [Spring configuration checklist](spring-configuration-audit.md) for profile, import, launch, and source checks.

## 3. Place Spring settings

This is a settings fragment. Use the runtime schema for the surrounding node.

```json
{
  "vmOptions": ["-Xmx512m"],
  "vmProperties": {
    "spring.profiles.active": "local",
    "company.runtime.mode": "local"
  },
  "springProperties": {
    "server.port": 18090,
    "clients.payment.timeout": 3000,
    "app.labels": ["local", "isolated"],
    "app.password": {"fromEnv": "LOCAL_APP_PASSWORD"}
  }
}
```

- Use property names as top-level Spring keys and preserve JSON scalar, list, and map types. Use dotted keys for leaf overrides.
- Merge defaults, variant, node profile overrides, and root profile overrides in that order. Later values replace whole keys. The applicable Spring Boot version controls binding between source and generated settings.
- Check for environment and VM settings that shadow Spring keys. Injector detects exact VM names and standard environment transformations. It does not evaluate all binding aliases, inherited values, or program arguments.
- Keep JVM property readers in `vmProperties`. For dependency addresses, use schema 1.1 `injections` with `springProperty` and node, endpoint, context, and component.
- Render writes separate YAML and adds `spring.config.additional-location`. Preserve source YAML and investigate any existing additional location. Put `spring.config.*` bootstrap settings and profile selection in JVM properties or environment.
- Use `fromEnv` for secrets. Generated YAML has `${ENV_NAME}`; the app environment supplies the value. Keep real credentials out of registry files, diagnostics, and commits.

YAML rendering currently supports IntelliJ targets. Compose YAML and container path translation remain outside support. Injector rejects secret environment or JVM properties that would be persisted to XML. Record unsupported inputs as findings.

`prepare <app-id> --project <repo> --registry <registry-folder> --profile <profile>` prepares dependencies and generates Debug settings. The registration workflow uses static verification. Open the UI with `Start-Injector.vbs` or `serve --open` and specify both folders.

Dependencies use process, Compose, or external runners. An IntelliJ dependency needs a process or Compose variant for automatic startup. Compose environment settings are merged, and JVM options are defined in its service command. Process JVM options require `java`. Use a dedicated Compose project name and check host port conflicts. `--mode dummy/real` are profile aliases.

## 4. Update with evidence

1. Confirm the app ID, profile, variant, and existing user-approved settings.
2. Record file and line, consumer, profile, local purpose, and channel in findings. Keep raw secrets out.
3. Register app and infrastructure nodes and endpoints and link them by ID. Reuse shared database or broker IDs.
4. Write confirmed local settings. Keep unknowns as questions without guessed ports, main classes, or null required values.
5. Review the diff and verify existing settings and affected shared dependencies.

## 5. Verify and report

Substitute real paths and IDs. Validate checks structure, plan computes the order, and check resolves declared settings and inspects runner requirements for the selected app. Those three commands leave runtime state and source files untouched. Resolve reads environment references and reports redacted provenance. Render generates files without starting the app.

```text
python <Injector>/injector.py validate --project <target> --registry <registry-folder>
python <Injector>/injector.py plan <app-id> --project <target> --registry <registry-folder> --profile <profile>
python <Injector>/injector.py check <app-id> --project <target> --registry <registry-folder> --profile <profile>
python <Injector>/injector.py resolve --project <target> --registry <registry-folder> --profile <profile> --node <node>
python <Injector>/injector.py render --project <target> --registry <registry-folder> --profile <profile> --node <node>
```

With external storage, outputs go under `.local/injector/<worktree-id>/` in the registry directory. Import the generated configuration into IntelliJ for Debug. Regeneration replaces generated files.

Report changed apps and profiles, performed checks, unknown inputs, unsupported readers, and whether the app was started. Use real source evidence from the project provided.

`validate` and `plan` can pass even when a required `fromEnv` variable is unavailable. If `resolve` reports a missing reference without naming it, inspect the selected node's effective settings and list the applicable reference names and source locations. Where authorized, check presence in the intended launch environment without printing values. The current shell and the IntelliJ launch may have different environments. Ask who supplies any remaining variable and record the blocked scope.
