"""Read saved web suite reports from Injector's evidence directory."""
import json
from pathlib import Path
import re

from injector_core.observation_contract import MAX_OBSERVATION_BYTES
from injector_core.registry import RegistryError, _parse_json
from injector_core.rendering import _artifact_path


_RUN_ID = re.compile(r"[a-f0-9]{16}")
_RUN_LIMIT = 20


def _read(root, path):
    _artifact_path(root, path)
    limit = 4 * MAX_OBSERVATION_BYTES
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise RegistryError("검증 보고서가 표시 용량을 초과했습니다.")
    data = _parse_json(content.decode("utf-8"))
    if not isinstance(data, dict):
        raise RegistryError("검증 보고서 형식을 확인하세요.")
    return data


def _case_path(directory, cases, index):
    relative = f"{index:02}/report.json"
    if not 1 <= index <= len(cases) or cases[index - 1].get("report") != relative:
        raise RegistryError("이 시나리오에는 저장된 증거가 없습니다.")
    return directory / relative


def _value_at(document, pointer):
    value = document
    try:
        for token in pointer.split("/")[1:]:
            key = token.replace("~1", "/").replace("~0", "~")
            if isinstance(value, list):
                if not re.fullmatch(r"0|[1-9][0-9]*", key):
                    return None
                key = int(key)
            value = value[key]
    except (IndexError, KeyError, TypeError, ValueError):
        return None
    preview = json.dumps(value, ensure_ascii=False)
    return preview if len(preview) <= 160 else preview[:159] + "…"


def _suite(root, directory, project):
    report = _read(root, directory / "report.json")
    cases = report.get("cases")
    if (report.get("schemaVersion") != 1 or not isinstance(cases, list) or not 1 <= len(cases) <= 16
            or any(not isinstance(case, dict) for case in cases)
            or not all(isinstance(report.get(key), str) for key in ("suite", "targetApp", "profile", "verdict"))):
        raise RegistryError("스위트 보고서 형식을 확인하세요.")
    worktrees = report.get("worktrees")
    if not isinstance(worktrees, dict):
        # Older reports record checkout identities alongside the first comparison.
        comparison = _read(root, _case_path(directory, cases, 1))
        runs = comparison.get("runs")
        if not isinstance(runs, dict):
            raise RegistryError("보고서에서 워크트리를 확인할 수 없습니다.")
        worktrees = {side: run.get("project") for side, run in runs.items()
                     if isinstance(run, dict)}
    baseline = worktrees.get("baseline")
    if not isinstance(baseline, str) or Path(baseline).resolve() != project:
        raise RegistryError("이 프로젝트의 검증 보고서를 선택하세요.")
    return {**report, "worktrees": worktrees}


def saved_runs(root, project):
    root = root.resolve()
    project = Path(project).resolve()
    recent = []
    for path in root.glob("*/report.json"):
        if not _RUN_ID.fullmatch(path.parent.name):
            continue
        try:
            _artifact_path(root, path)
            recent.append((path.stat().st_mtime, path.parent))
        except (OSError, ValueError, RuntimeError):
            continue
    runs = []
    for modified, directory in sorted(recent, reverse=True):
        try:
            report = _suite(root, directory, project)
        except (OSError, ValueError, RuntimeError):
            continue
        runs.append({"id": directory.name, "modified": modified, "suite": report["suite"],
                     "targetApp": report["targetApp"], "profile": report["profile"], "verdict": report["verdict"]})
        if len(runs) == _RUN_LIMIT:
            break
    return runs


def saved_run(root, project, run, case=None):
    if not isinstance(run, str) or not _RUN_ID.fullmatch(run) or (case is not None and type(case) is not int):
        raise RegistryError("저장된 실행과 시나리오를 선택하세요.")
    root = root.resolve()
    directory = root / run
    try:
        report = _suite(root, directory, Path(project).resolve())
        if case is None:
            return report
        comparison = _read(root, _case_path(directory, report["cases"], case))
        changes = comparison.get("changes", [])
        if not isinstance(changes, list) or any(not isinstance(change, dict) or not isinstance(change.get("path"), str)
                                                for change in changes):
            raise RegistryError("관측 차이의 형식을 확인하세요.")
        for change in changes:
            for side in ("baseline", "candidate"):
                change[side] = _value_at(comparison[side], change["path"]) if side in comparison else None
        for side in ("baseline", "candidate"):
            if side in comparison:
                comparison[side] = json.dumps(comparison[side], ensure_ascii=False, indent=2)
        return comparison
    except (OSError, UnicodeError) as error:
        raise RegistryError("저장된 검증 보고서를 읽을 수 없습니다.") from error
