"""Run a reviewed suite using isolated paired Injector sessions."""
from pathlib import Path

from injector_core.observation import (_comparison_projects, _plan_observation, _run_comparison,
                                       _validate_fix_check, _write_artifact)
from injector_core.observation_contract import read_document
from injector_core.registry import RegistryError, registry_path
from injector_core.resolution import MissingEnvironmentReference
from injector_core.runtime import (ExecutionRequirementError, check_observation_idle, check_recording_requirements,
                                   select_plan)


_INPUT_ERRORS = (OSError, ValueError, RecursionError)


class SuitePreflightError(RegistryError):
    def __init__(self, report):
        self.report = report
        first = report["diagnostics"][0]
        prefix = f"suite case {first['case']}: " if "case" in first else ""
        super().__init__(prefix + first["message"])


def _diagnostic(report, code, error, **location):
    cause = error.__cause__
    if isinstance(cause, MissingEnvironmentReference):
        code = "missing_environment"
        location["variable"] = cause.variable
    if isinstance(error, ExecutionRequirementError):
        location["node"] = error.node
        if error.port is not None:
            code = "port_in_use"
            location["port"] = error.port
    message = str(error) if isinstance(error, RegistryError) else "could not read or inspect the selected input"
    report["diagnostics"].append({"code": code, "message": message, **location})
    report.update(status="BLOCKED", exitCode=2)


def _plan_suite(suite_path, project, candidate, registry):
    report = {"schemaVersion": 1, "phase": "preflight", "status": "BLOCKED", "exitCode": 2,
              "worktrees": {}, "cases": [], "diagnostics": []}
    try:
        suite_file = Path(suite_path).resolve()
        report["suiteFile"] = str(suite_file)
        suite = read_document(suite_file, "suite")
    except _INPUT_ERRORS as error:
        _diagnostic(report, "invalid_suite", error)
        return report, {}, []

    target, profile = suite["target"], suite["profile"]
    report.update(suite=suite["name"], targetApp=target, profile=profile)
    try:
        checkouts = _comparison_projects(project, candidate)
    except _INPUT_ERRORS as error:
        _diagnostic(report, "invalid_worktrees", error)
        checkouts = {}
    plans = {}
    variants = {}
    for side, checkout in checkouts.items():
        entry = report["worktrees"][side] = {"project": str(checkout)}
        try:
            entry["registry"] = str(registry_path(checkout, registry))
            data, plan = select_plan(checkout, target, profile, registry=registry)
        except _INPUT_ERRORS as error:
            _diagnostic(report, "invalid_registry", error, side=side)
            continue
        plans[side] = data, plan
        variants[side] = {step["node"]: step["variant"] for step in plan["steps"]}
        entry.update(order=plan["order"], variants=variants[side])
        try:
            check_observation_idle(checkout, registry=registry)
        except _INPUT_ERRORS as error:
            _diagnostic(report, "session_blocked", error, side=side)
            continue
        try:
            check_recording_requirements(checkout, target, data, plan, registry=registry)
        except _INPUT_ERRORS as error:
            _diagnostic(report, "execution_blocked", error, side=side)
    if len(variants) == 2 and variants["baseline"] != variants["candidate"]:
        _diagnostic(report, "incompatible_variants", RegistryError("the worktree variant selections differ"))

    prepared = []
    names = set()
    for index, case in enumerate(suite["cases"], start=1):
        entry = {"index": index, "file": case["scenario"]}
        report["cases"].append(entry)
        try:
            scenario = read_document(suite_file.parent / case["scenario"], "scenario")
        except _INPUT_ERRORS as error:
            _diagnostic(report, "invalid_scenario", error, case=index, file=case["scenario"])
            continue
        name = entry["scenario"] = scenario["name"]
        if name in names:
            _diagnostic(report, "duplicate_scenario", RegistryError(f"duplicate scenario name '{name}'"), case=index)
            continue
        names.add(name)
        if "proveFix" in case:
            entry["fixCheck"] = case["proveFix"]
        try:
            _validate_fix_check(scenario, entry.get("fixCheck"))
        except RegistryError as error:
            _diagnostic(report, "invalid_fix_check", error, case=index, check=entry["fixCheck"])
            continue
        observations = {}
        for side, (data, plan) in plans.items():
            try:
                observations[side] = _plan_observation(scenario, data, plan)
            except _INPUT_ERRORS as error:
                _diagnostic(report, "unsupported_scenario", error, case=index, side=side)
        prepared.append(observations)

    if not report["diagnostics"]:
        report.update(status="READY", exitCode=0)
    return report, checkouts, prepared


def check_suite(suite_path, project, candidate, *, registry=None):
    report, _, _ = _plan_suite(suite_path, project, candidate, registry)
    return report


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
    preflight, checkouts, prepared = _plan_suite(suite_path, project, candidate, registry)
    destination = Path(output)
    if destination.exists() or destination.is_symlink():
        _diagnostic(preflight, "output_exists", RegistryError("suite output directory already exists"))
    if preflight["status"] != "READY":
        raise SuitePreflightError(preflight)

    target, profile = preflight["targetApp"], preflight["profile"]
    cases = [{**{key: case[key] for key in ("scenario", "fixCheck") if key in case}, "verdict": "NOT_RUN"}
             for case in preflight["cases"]]

    try:
        destination.mkdir(parents=True)
    except FileExistsError as error:
        _diagnostic(preflight, "output_exists", RegistryError("suite output directory already exists"))
        raise SuitePreflightError(preflight) from error
    except OSError as error:
        _diagnostic(preflight, "output_unavailable", RegistryError("could not create the suite output directory"))
        raise SuitePreflightError(preflight) from error
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
        report = {"schemaVersion": 1, "suite": preflight["suite"], "targetApp": target, "profile": profile,
                  "verdict": verdict, "counts": counts, "cases": cases, "report": str(report_path),
                  "summary": str(summary_path)}
        _write_artifact(report_path, report)
        _write_summary(summary_path, report)
    return report
