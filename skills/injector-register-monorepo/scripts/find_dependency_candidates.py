"""List source locations for dependency review without running the target project."""

import argparse
import json
import os
from pathlib import Path
import re


SOURCE_TYPES = {".java", ".kt"}
CONFIG_TYPES = {".properties", ".yaml", ".yml"}
EXCLUDED_DIRS = {".git", ".gradle", ".idea", ".local", ".venv", "build", "node_modules", "out", "target", "vendor"}
SOURCE_RULES = {
    "http-client": r"\b(?:FeignClient|WebClient|RestClient|RestTemplate|HttpClient|OkHttpClient|Retrofit)\b",
    "kafka-client": r"\b(?:KafkaListener|KafkaTemplate|KafkaProducer|KafkaConsumer|ProducerRecord)\b",
    "database-client": r"\b(?:JdbcTemplate|NamedParameterJdbcTemplate|DataSource|DriverManager|EntityManager)\b|\bjdbc:",
    "redis-client": r"\b(?:Jedis\w*|RedisTemplate|StringRedisTemplate|RedisConnectionFactory|RedisClient|RedissonClient)\b",
    "vault-client": r"\b(?:VaultTemplate|VaultOperations|VaultEndpoint)\b|/v1/[^/\s]+/data/",
    "setting-reference": r"@(?:Value|ConfigurationProperties)\b|\bSystem\.(?:getenv|getProperty)\s*\(",
}
CONFIG_RULES = {
    "connection-setting": r"(?:^|[.\s_-])(?:url|uri|endpoint|host|port|ports|bootstrap[-_.]servers)[\"']?\s*[:=]",
    "infrastructure-setting": (
        r"^\s*[\"']?(?:(?:spring[._-](?:(?:data|cloud)[._-])?)?"
        r"(?:datasource|kafka|redis|vault|configserver)|kafka[_-](?:advertised[_-])?listeners)[\"']?\s*[:=]|\bjdbc:"
    ),
    "configuration-import": r"(?:^|[.\s])(?:import|additional-location)[\"']?\s*[:=]",
}


def scan(root, scopes, source_rules):
    matches = []
    skipped = {}
    seen = set()
    rules_by_type = {suffix: source_rules for suffix in SOURCE_TYPES}
    config_rules = {kind: re.compile(pattern, re.IGNORECASE) for kind, pattern in CONFIG_RULES.items()}
    rules_by_type.update({suffix: config_rules for suffix in CONFIG_TYPES})
    files_scanned = 0

    def relative(path):
        return path.relative_to(root).as_posix()

    def read(path):
        nonlocal files_scanned
        rules = rules_by_type.get(path.suffix.lower())
        if not rules or path in seen or path.is_symlink() or not path.is_file():
            return
        seen.add(path)
        try:
            with path.open(encoding="utf-8-sig", errors="replace") as source:
                for line_number, line in enumerate(source, 1):
                    if line.lstrip().startswith(("//", "/*", "*", "#", "!", "import ")):
                        continue
                    matches.extend({"path": relative(path), "line": line_number, "rule": rule}
                                   for rule, pattern in rules.items() if pattern.search(line))
            files_scanned += 1
        except OSError:
            skipped[relative(path)] = "unreadable file"

    def walk_error(error):
        skipped[relative(Path(error.filename))] = "unreadable directory"

    for scope in scopes:
        if scope.is_file():
            read(scope)
            continue
        for directory, dirs, files in os.walk(scope, onerror=walk_error):
            folder = Path(directory)
            dirs[:] = sorted(name for name in dirs
                             if name not in EXCLUDED_DIRS and not (name == "test" and folder.name == "src")
                             and Path(os.path.realpath(folder / name)) == folder / name)
            for name in sorted(files):
                read(folder / name)

    return {"scopes": [relative(scope) for scope in scopes], "filesScanned": files_scanned,
            "matches": sorted(matches, key=lambda item: (item["path"], item["line"], item["rule"])),
            "skipped": [{"path": path, "reason": reason} for path, reason in sorted(skipped.items())]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="source repository root")
    parser.add_argument("--scope", type=Path, action="append", help="repo-relative file or folder, repeatable")
    parser.add_argument("--source-pattern", metavar="NAME=REGEX", action="append", default=[],
                        help="additional Java or Kotlin search rule, repeatable")
    args = parser.parse_args()
    root = args.project.resolve()
    if not root.is_dir():
        parser.error("project root must be an existing directory")

    scopes = []
    for requested in args.scope or [Path(".")]:
        scope = (root / requested).resolve()
        if requested.is_absolute() or not scope.is_relative_to(root) or not (scope.is_file() or scope.is_dir()):
            parser.error("--scope must name an existing relative file or folder inside the project")
        scopes.append(scope)

    rules = {kind: re.compile(pattern) for kind, pattern in SOURCE_RULES.items()}
    for entry in args.source_pattern:
        name, _, pattern = entry.partition("=")
        if not re.fullmatch(r"[a-z][a-z0-9-]*", name) or not pattern or name in rules:
            parser.error("--source-pattern requires a unique lowercase NAME=REGEX")
        try:
            rules[name] = re.compile(pattern)
        except re.error as error:
            parser.error(f"invalid regular expression for {name}: {error.msg}")
    print(json.dumps(scan(root, scopes, rules), indent=2))


if __name__ == "__main__":
    main()
