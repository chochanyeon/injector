# Injector development workflow

**English** · [한국어](AGENTS.ko.md)

- Start with the [work index](docs/index.md). Select the T-ID and read its design, development, verification, and resume point.
- Develop Injector at the repository root. Keep the example target under `examples/demo/`.
- Support macOS as the primary platform and support Windows alongside it. Check both platforms and their documentation when changing launchers, installation, or system paths.
- Make routine registration and verification usable by an LLM through documented, non-interactive commands, structured results, and saved evidence. Use the same runtime for web and CLI workflows. [Automation criteria](docs/work-items/T-380.md)
- Distinguish implemented behavior from planned work. Check the current implementation before claiming graph execution, application registration, or related features are complete.
- Set a T-ID and acceptance criteria at the start of a work item. Record decisions, changed files, verification evidence, and next actions in that work item's document. Keep the index and project status in sync.
- Verify tests and runtime state directly. Recheck containers, IntelliJ, and installed skill copies when resuming a session.
- Commit and push each verified work item to `https://github.com/chochanyeon/injector`. Keep generated files, build outputs, and real credentials out of commits.
- Make changes within the requested scope and document decisions that matter. Follow the user's latest instructions.
- Use English for default Markdown paths and keep the Korean translation in a sibling `*.ko.md` file. Link the two versions and update both when changing shared documentation.
