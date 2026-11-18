---
name: injector-register-monorepo
description: Initialize Injector registration for a monorepo or update an existing registry. Discover runnable modules, trace Spring and JVM configuration to its sources, and record dependencies and injection rules with evidence. The workflow does not launch services.
---

# Register a monorepo with Injector

**English** · [한국어](SKILL.ko.md)

Discover existing runtime definitions and produce a reviewable draft or a reviewed runtime registry when requested.

- For first-time registration, follow the [monorepo discovery guide](references/monorepo-initialization.md). Start with the requested app or subtree, reconstruct its chosen launch, and follow only relevant cross-boundary dependencies.
- For Spring apps, use the [Spring configuration checklist](references/spring-configuration-audit.md) to compare sources and consumers for the selected runner.
- For drafts, use the [registration protocol](references/registration-protocol.md) and [example JSON](assets/registration-draft.example.json). For reviewed runtime files, use the [runtime registry guide](references/runtime-registry-guide.md) to check the schema and commands.

## Scope

Start with the requested monorepo, app, build files, and launch definitions. Store registry files and research under Injector's `registries/<repo-id>/`. Use `--project` for the source worktree and `--registry` for the settings directory. Static analysis reads source to gather evidence. Build or service startup, container launch, and hosts or DNS changes are outside this workflow.

Draft v0.1 is a discovery artifact. Runtime files follow the current Injector schema. Check its supported fields and leave unresolved values in findings. The legacy `project.json` is the demo configuration.

## Investigate and record

1. Classify runnable apps and libraries. Find entry point, working directory, and active profiles.
2. Trace endpoints and keys through JVM options, environment variables, configuration files, references, and defaults.
3. Identify runtime dependencies separately from build dependencies and follow them recursively.
4. Construct the graph for the selected mode, profile, and caller context. Check shared nodes, cycles, port collisions, and unresolved references.
5. Produce a draft and findings with file and line evidence, inferences, unknowns, and questions ordered by their effect on execution.

When updating, preserve node IDs and user-confirmed values. Report differences in new evidence and retain existing settings for review.

## Completion

Check JSON, references, file and line evidence, and DFS order. Set `startupOrder` to `null` when cycles or unknown edges prevent ordering and record the reason. Keep partial findings and exact questions for unresolved inputs. For runtime registration, compare the actual `plan` to the intended local scenario and report remaining configuration or startup checks separately.
