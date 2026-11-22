"""Run a reviewed suite using isolated paired Injector sessions."""
from pathlib import Path

from injector_core.observation import _comparison_projects, _plan_comparison, _run_comparison, _write_artifact
from injector_core.observation_contract import read_document
from injector_core.registry import RegistryError


def _write_summary(path, report):
    lines = [f"# {report['suite']}", "", f"**{report['verdict']}** · `{report['targetApp']}` · `{report['profile']}`",
             "", "| Scenario | Check | Verdict | Evidence |", "| --- | --- | --- | --- |"]
    for entry in report["cases"]:
        check = f"Fix `{entry['fixCheck']}`" if "fixCheck" in entry else "Parity"
        links = [f"[Case report]({entry['report']})"] if "report" in entry else []
        links.extend(f"[{side.capitalize()}]({artifact})" for side, artifact in entry.get("artifacts", {}).items())
        evidence = " · ".join(links)
        lines.append(f"| `{entry['scenario']}` | {check} | `{entry['verdict']}` | {evidence} |")
    lines.extend(("", "[Machine-readable report](report.json)", ""))
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines))


def verify_suite(suite_path, project, candidate, output, *, registry=None, emit=lambda scenario, side: None):
    suite_file = Path(suite_path).resolve()
    suite = read_document(suite_file, "suite")
    checkouts = _comparison_projects(project, candidate)
    destination = Path(output)
    if destination.exists() or destination.is_symlink():
        raise RegistryError("suite output directory already exists")

    target, profile = suite["target"], suite["profile"]
    prepared = []
    cases = []
    names = set()
    for index, case in enumerate(suite["cases"], start=1):
        try:
            scenario = read_document(suite_file.parent / case["scenario"], "scenario")
            name = scenario["name"]
            if name in names:
                raise RegistryError(f"duplicate scenario name '{name}'")
            names.add(name)
            fix = case.get("proveFix")
            observations = _plan_comparison(checkouts, target, profile, scenario, registry, fix)
        except RegistryError as error:
            raise RegistryError(f"suite case {index}: {error}") from error
        prepared.append(observations)
        summary = {"scenario": name, "verdict": "NOT_RUN"}
        if fix is not None:
            summary["fixCheck"] = fix
        cases.append(summary)

    try:
        destination.mkdir(parents=True)
    except FileExistsError as error:
        raise RegistryError("suite output directory already exists") from error
    report_path = destination / "report.json"
    summary_path = destination / "summary.md"
    try:
        for index, (entry, observations) in enumerate(zip(cases, prepared), start=1):
            case_dir = destination / f"{index:02}"
            case_report = case_dir / "report.json"
            entry.update(verdict="INCONCLUSIVE", reason="comparison did not complete")
            try:
                result = _run_comparison(checkouts, target, profile, observations, case_dir, registry=registry,
                                         prove_fix=entry.get("fixCheck"), emit=lambda side: emit(entry["scenario"], side))
            except KeyboardInterrupt:
                entry["reason"] = "execution interrupted"
                raise
            finally:
                if case_report.is_file():
                    entry["report"] = case_report.relative_to(destination).as_posix()
                artifacts = {side: f"{case_dir.name}/{side}.json" for side in checkouts
                             if (case_dir / f"{side}.json").is_file()}
                if artifacts:
                    entry["artifacts"] = artifacts
            entry["verdict"] = result["verdict"]
            entry.pop("reason")
            if "reason" in result:
                entry["reason"] = result["reason"]
            if result.get("changeCount"):
                entry["changeCount"] = result["changeCount"]
            if any(run["status"] != "recorded" for run in result["runs"].values()):
                break
    finally:
        counts = dict.fromkeys(("PASS", "FAIL", "INCONCLUSIVE", "NOT_RUN"), 0)
        for entry in cases:
            counts[entry["verdict"]] += 1
        verdict = "FAIL" if counts["FAIL"] else "PASS" if counts["PASS"] == len(cases) else "INCONCLUSIVE"
        report = {"schemaVersion": 1, "suite": suite["name"], "targetApp": target, "profile": profile,
                  "verdict": verdict, "counts": counts, "cases": cases, "report": str(report_path),
                  "summary": str(summary_path)}
        _write_artifact(report_path, report)
        _write_summary(summary_path, report)
    return report
