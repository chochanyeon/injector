# Work index

**English** · [한국어](index.ko.md)

Last updated November 23, 2026. Each T-ID groups design, development, verification, and the point at which to resume.

## 1. Work items

Follow the order below. T-130, T-131, and T-140 were prioritized after T-040 at the user's request. T-150 followed T-060 to add the browser workflow. Each work item lists its prerequisites.

| Work ID | Work item | Design | Development | Verification |
|---|---|---|---|---|
| [T-000](work-items/T-000.md) | Single-demo POC | Complete for POC | Complete | Complete for documented scope |
| [T-005](work-items/T-005.md) | LLM monorepo onboarding and Spring configuration audit | Complete for discovery | Complete | Format, examples, and scoped walkthrough verified |
| [T-010](work-items/T-010.md) | Application registry schema | Complete | Complete | Schema verified |
| [T-020](work-items/T-020.md) | Registry loading, validation, and project selection | Complete | Complete | Loading and references verified |
| [T-030](work-items/T-030.md) | Endpoint resolution and settings injection | Complete | Complete | Resolution and merge verified |
| [T-040](work-items/T-040.md) | DFS execution planning | Complete | Complete | Planning verified |
| [T-130](work-items/T-130.md) | WireMock-based Vault configuration API mock | Complete for the request contract | Complete | KV v2 demo verified |
| [T-131](work-items/T-131.md) | Service-specific Vault paths and values | Complete | Complete | Two-service demo verified |
| [T-140](work-items/T-140.md) | External Spring YAML and AI-assisted registry maintenance | Complete | Complete for local IntelliJ generation | Verified with Spring Boot |
| [T-050](work-items/T-050.md) | Execution and readiness checks | Complete for initial execution | Complete | Documented scope verified |
| [T-060](work-items/T-060.md) | Target app execution pipeline | Complete for supported runners | Complete | New IDE Debug flow pending |
| [T-150](work-items/T-150.md) | Browser environment preparation | Complete | Complete | Manual browser verification pending |
| [T-070](work-items/T-070.md) | Custom hostnames | Complete for hosts on macOS and Windows | Complete | System changes with elevation pending |
| [T-160](work-items/T-160.md) | macOS and Windows launch support | Complete | Complete | Finder and IDE checks pending |
| [T-170](work-items/T-170.md) | Local registry.json editor | Complete | Complete | macOS picker pending |
| [T-180](work-items/T-180.md) | Registry dependency graph | Complete | Complete | Small viewport and large graph checks pending |
| [T-190](work-items/T-190.md) | Per-app execution and settings files | Complete | Complete | Compatibility, editor, and processes verified |
| [T-200](work-items/T-200.md) | Separate registry storage from source worktrees | Complete | Complete | Native picker and IDE import checks pending |
| [T-210](work-items/T-210.md) | English and Korean documentation | Complete | Complete | Language navigation and links verified |
| [T-220](work-items/T-220.md) | Check registry execution requirements | Complete | Complete | See test results and limits in the work item |
| [T-230](work-items/T-230.md) | Fix execution and validation issues found in review | Complete | Complete | Compose, CLI, and browser regression checks |
| [T-240](work-items/T-240.md) | Remember the selected project and registry | Complete | Complete | Server restart and browser load regression checks |
| [T-080](work-items/T-080.md) | Per-dependency real or mock execution | Complete | Complete | Demo and process scenarios verified |
| [T-090](work-items/T-090.md) | Session, failure, and stop policies | Complete for session ownership | Complete | Windows regression and Docker identity verified |
| [T-100](work-items/T-100.md) | LLM registration draft validation and conversion | Complete for one reviewed profile | Complete | Converter and skill verified |
| [T-110](work-items/T-110.md) | Multi-app integration verification | Complete for the portable fixture | Complete | Windows integration verified |
| [T-120](work-items/T-120.md) | Automatic preparation before IDE execution | Complete for JVM Application configurations | Complete | CLI regression and IDE exit-code contract verified |
| [T-250](work-items/T-250.md) | Bring Injector and Verifier into one repository | Complete | Complete | Source history and Gradle tests verified |
| [T-260](work-items/T-260.md) | Observe and compare one local HTTP dependency | Complete for one edge | Complete | CLI, API and Edge demo verified |
| [T-270](work-items/T-270.md) | Multi-service shop monorepo demo | Complete | Complete | Windows Docker and JVM integration verified |
| [T-280](work-items/T-280.md) | Shop demo Vault and log integration | Complete | Complete | Windows Vault settings and HTTP-to-Kafka log correlation verified |
| [T-290](work-items/T-290.md) | Vault settings for every shop service | Complete | Complete | Six startup reads verified in both profiles |
| [T-300](work-items/T-300.md) | Review fixes for execution and comparison | Complete | Complete | Five regressions and both shop profiles verified |
| [T-310](work-items/T-310.md) | Compare one HTTP scenario across worktrees | Complete | Complete | Live Git worktree comparison verified on Windows |
| [T-320](work-items/T-320.md) | Check registry execution requirements from the CLI | Complete | Complete | Windows CLI and live Compose configuration verified |
| [T-330](work-items/T-330.md) | Compare a correlated HTTP and Kafka trace | Complete | Complete | Live PASS, downstream change and missing consumer verified |
| [T-340](work-items/T-340.md) | Search for dependency evidence during registration | Complete | Complete | Shop, scoped fixture, and installed copy verified |
| [T-350](work-items/T-350.md) | Verify a fix with reproducible checkout evidence | Complete for one scenario | Complete | Windows Docker and JVM fix verification complete |
| [T-360](work-items/T-360.md) | Run a fix and its regression scenarios together | Complete | Complete | Windows process and live shop suite verified |
| [T-370](work-items/T-370.md) | Verify required and forbidden event counts | Complete | Complete | Live Windows suite verified Kafka counts of one and zero |
| [T-380](work-items/T-380.md) | Run registration and verification without manual prompts | Preflight defined | Partial | Shared suite preflight and CLI verified on Windows |
| [T-390](work-items/T-390.md) | Build and run the full test environment | Complete | Complete | All 13 stages passed on Windows. Native macOS run pending |
| [T-400](work-items/T-400.md) | Run and inspect local work in the web dashboard | Complete | Complete | Windows Chrome desktop and narrow layouts verified |
| [T-410](work-items/T-410.md) | Reopen saved verification evidence from the dashboard | Complete | Complete | Complete |
| [T-420](work-items/T-420.md) | Registry editor autocomplete | Complete | Complete | Windows desktop verified |
| [T-430](work-items/T-430.md) | Shut down the web server from the dashboard | Complete | Complete | Windows VBS and Chrome verified |

Completion applies to the scope documented in each row. Drafts define scope and acceptance criteria. Detailed designs follow.

## 2. Work item format

Each `work-items/T-xxx.md` includes:

1. **Design** explains the problem, scope, requirements, options, rationale, and acceptance criteria.
2. **Development** lists changed files, implementation details, and remaining work.
3. **Verification** separates plans from actual commands, environments, results, and limitations.
4. **Resume point** records open issues and the next action.

Keep decisions and evidence under the same T-ID. Link larger supporting documents from the work item when needed.

## 3. Resume development

Continue the non-interactive workflow for a registered target. Suite preflight now returns structured diagnostics. The next step is to classify runtime startup and cleanup results for automation. Verify on a work monorepo and check the imported External Tool configuration on macOS. [T-380](work-items/T-380.md) · [T-120](work-items/T-120.md)

1. Check `git status --short --branch` and recent commits. Identify the context of any uncommitted changes.
2. Choose a T-ID and read it from design through the resume point. Consult the shared references as needed.
3. Confirm prerequisites and acceptance criteria. Follow the latest user instructions.
4. Install dependencies with `python -m pip install -r requirements.txt`. Run `python -m unittest discover -s tests -v` and any work-specific checks. The Windows baseline passed 113 tests with the Vault URL and Spring JAR and JDK configured.
5. Write decisions, implementation, evidence, and next steps in the work item. Update this index and the project status.
6. Commit, push, and verify the remote. Record the resume point before pausing.

Recheck live containers, IntelliJ, and the locally installed skill. Unit tests run without Docker or IntelliJ.

## 4. Shared references

- [Design](design.md) for shared R-IDs, D-IDs, and architecture.
- [Project status](status.md) for the current implementation, limits, and handoff.
- [Verification history](validation-history.md) for earlier T-000 and T-005 procedures.
- [README](../README.md) for the current workflow.
- [Registration skill](../skills/injector-register-monorepo/SKILL.md) for monorepo onboarding, Spring configuration discovery, and registry maintenance.

## 5. Status and change rules

Track design as draft, in progress, or complete. Track development as not started, in progress, partial, or complete. Track verification as not run, in progress, failed, partial, or complete. Candidate items have an open scope or start date. Record what was actually verified and the limits of each result.

Keep T-IDs stable. Add a work item and an index row together. Record rationale and impact when changing the design. Database seeding, topic initialization, non-HTTP mocks, forced outbound blocking, and support for all languages and IDEs remain open.

English is the default document path. Update the corresponding Korean `*.ko.md` file when changing shared documentation.
