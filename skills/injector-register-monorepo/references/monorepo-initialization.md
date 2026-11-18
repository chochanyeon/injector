# First-time monorepo registration

**English** · [한국어](monorepo-initialization.ko.md)

Identify the monorepo root, the first app to debug, the runner, and its profiles. If the target is open, report candidates and evidence. For repository-wide registration, inventory candidates first and verify apps one dependency subgraph at a time.

## 1. Discover runnable apps

- Use `rg --files` to locate Gradle settings, Maven POMs, launch scripts, shared IntelliJ settings, Dockerfiles, and Compose. Exclude build output and vendor directories.
- Follow Gradle `include`, remapped `projectDir`, and `includeBuild`. Check convention plugins or `buildSrc` for application plugins, entry points, and resource directories. [Gradle multi-project builds](https://docs.gradle.org/current/userguide/multi_project_builds.html) · [Gradle composite builds](https://docs.gradle.org/current/userguide/composite_builds.html)
- Follow Maven aggregator `modules`, modules added by profiles, and inherited launcher settings in parent POMs. Record aggregation and inheritance evidence separately. [Maven multi-module builds](https://maven.apache.org/guides/mini/guide-multiple-modules.html) · [Maven build profiles](https://maven.apache.org/guides/introduction/introduction-to-profiles.html)
- Confirm each entry point and how it runs independently. Classify libraries, aggregators, test apps, and one-off jobs. Leave dynamic modules and commands unresolved when static evidence is insufficient.

Record ID, module path, kind, launch evidence with file and line, and investigation status. Keep an app's ID stable across worktrees.

## 2. Inspect the target and infrastructure

1. Check entry point, working directory, command or IntelliJ module, profiles, bind port, and readiness. Set `projectPath` from the actual IntelliJ project root.
2. Find databases, Kafka, Redis, Vault, Config Server, and other prerequisite resources. Check whether they are shared and where the caller runs. Distinguish published ports, internal ports, and service names. Use one node per shared resource.
3. Trace JVM options, environment variables, and configuration sources for each runner. Apply the [Spring checklist](spring-configuration-audit.md) where relevant. Capture cross-app calls as candidate edges.
4. Record the evidence, confirmed local values, and user decisions for needed inputs. Preserve existing confirmed settings and evidence.

## 3. Complete the app graph

- Locate each call in code and in the selected profile. Trace caller → service ID → endpoint and record build references separately.
- Distinguish startup or readiness calls from request-specific and background calls. Add edges for the selected local scenario to `dependencies` and link consumer keys with `injections`.
- For a shared broker, record the broker dependency first. Add producer or consumer apps when the scenario requires them.
- Record the real and mock dependency graphs separately. If real Catalog needs PostgreSQL and mock Catalog does not, the database drops out unless another selected path requires it.
- Record ambiguous edges and cycle paths with evidence. Injector computes execution order from the resolved graph.

## 4. Register and verify the first target

For discovery only, save draft and findings under Injector's `registries/<repo-id>/onboarding/`. For reviewed registry work, write `registry.json` and app and infrastructure files in the same registry directory. [Draft protocol](registration-protocol.md) · [Runtime guide](runtime-registry-guide.md)

Use the target repository as the source of evidence. Leave pending candidates in the inventory and identify the app, profile, key, and blocked choice for each question. Confirm the target and transitive dependencies' runners, endpoints, and configuration sources. Run `validate` for the project and profile and `plan` for the target. Check selections, startup order, shared nodes, and remaining external addresses. Record blockers and future apps, with static verification and actual IntelliJ Debug reported separately.
