# First-time monorepo registration

**English** · [한국어](monorepo-initialization.ko.md)

Identify the monorepo root, the first app to debug, the runner, and its profiles. If the target is open, report candidates and evidence. For repository-wide registration, inventory candidates first and verify apps one dependency subgraph at a time.

For a scoped request, start with that subtree and the build or launch definitions that govern it. Read a shared module or sibling app when a specific setting, build convention, or runtime call leads there. Record the reason and keep unrelated apps out of the registration. If several launches match the request, record the evidence for each and ask which one to use while continuing shared discovery.

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

Reconstruct one concrete launch before choosing values. Record the source module, runner and working directory, build selection, Spring profiles, and the Injector profile separately. Identify where each profile or argument is set. Trace shared conventions and launcher overrides back to their declarations. A source fallback remains a candidate until its activation condition is established.

## 3. Complete the app graph

- Locate each call in code and in the selected profile. Trace caller → service ID → endpoint and record build references separately.
- Distinguish startup or readiness calls from request-specific and background calls. Add edges for the selected local scenario to `dependencies` and link consumer keys with `injections`.
- For a shared broker, record the broker dependency first. Add producer or consumer apps when the scenario requires them.
- Record the real and mock dependency graphs separately. If real Catalog needs PostgreSQL and mock Catalog does not, the database drops out unless another selected path requires it.
- Record ambiguous edges and cycle paths with evidence. Injector computes execution order from the resolved graph.

For each relevant edge, record the caller's key or entry point, the activation condition, the provider identity and endpoint evidence, and the local decision (real, mock, external, or unresolved). Distinguish a startup requirement from a service used only by the requested request path or an enabled worker. Treat an external dependency as locally usable only after confirming its endpoint, readiness contract, and permission for the intended local scenario. Keep remote defaults visible in findings until an explicit local decision replaces or permits them.

## 4. Register and verify the first target

For discovery only, save draft and findings under Injector's `registries/<repo-id>/onboarding/`. For reviewed registry work, write `registry.json` and app and infrastructure files in the same registry directory. [Draft protocol](registration-protocol.md) · [Runtime guide](runtime-registry-guide.md)

Use the target repository as the source of evidence. Leave pending candidates in the inventory and identify the app, profile, key, and blocked choice for each question. Confirm the target and transitive dependencies' runners, endpoints, and configuration sources. Run `validate` for the project and profile and `plan` for the target. Check selections, startup order, shared nodes, and remaining external addresses. Record blockers and future apps, with static verification and actual IntelliJ Debug reported separately.

Before promoting a target, check the launch through both directions: follow its configuration sources to their consumers, then follow its enabled clients back to effective values and providers. Record which source categories were checked, absent, or inaccessible. Keep unknown required values, ambiguous providers, and unsupported injection channels in findings. Ask for the exact missing input or decision with its evidence and impact, and keep verified parts of the draft when blocked. Check the expected nodes and excluded branches against the plan, including a local mock's transitive consequences. A successful plan verifies the registered graph. Report any remaining settings, remote calls, and startup checks on their own evidence.
