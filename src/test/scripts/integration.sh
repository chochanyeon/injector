#!/usr/bin/env bash
# End-to-end checks against real Git worktrees, Gradle builds, and a Spring Boot backend.
set -Eeuo pipefail
tool=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd -P)
sandbox=$(mktemp -d /tmp/verifier-integration.XXXXXXXX)
trap 'rm -rf -- "$sandbox"' EXIT
repo="$sandbox/service with spaces"
mkdir -p "$repo"
for file in settings.gradle build.gradle upgrade-verifier.gradle gradlew gradlew.bat \
            gradle-wrapper.jar gradle-wrapper.properties .gitignore; do
    cp "$tool/$file" "$repo/"
done
mkdir -p "$repo/src/test/java/upgrade/fixture"
cp "$tool/src/test/java/upgrade/fixture/SampleApplication.java" "$repo/src/test/java/upgrade/fixture/"
# HEAD intentionally has neither the verifier source nor its init script.
git -C "$repo" init -q
git -C "$repo" add .
git -C "$repo" -c user.name=Verifier -c user.email=verifier@example.test commit -qm fixture
project_path=:
module_prefix=

run_case() {
    local expected=$1 status=0
    shift
    bash "$tool/verify-upgrade.sh" --repo "$repo" --project "$project_path" -- \
        '-Pverify.probe.classes=upgrade.verifier.VerifierMechanicsTest$BeanCountProbe' \
        "$@" >"$sandbox/stdout" 2>"$sandbox/stderr" || status=$?
    local actual
    actual=$(cat "$sandbox/stdout")
    if [[ $actual != "$expected" || $(wc -l < "$sandbox/stdout") != 1 \
          || ($expected == PASS && $status != 0) || ($expected == FAIL && $status != 1) ]]; then
        cat "$sandbox/stderr" >&2
        printf 'Unexpected verdict: %s / status %s (wanted %s)\n' "$actual" "$status" "$expected" >&2
        exit 1
    fi
    [[ $(git -C "$repo" worktree list --porcelain | awk '/^worktree / { n++ } END { print n }') == 1 ]]
    # The uncommitted dependency upgrade must survive every run.
    [[ $(git -C "$repo" show "HEAD:${module_prefix}build.gradle") == *commons-codec:1.18.0* ]]
    [[ $(cat "$repo/${module_prefix}build.gradle") == *commons-codec:1.19.0* ]]
}

# Upgrade a library used by the GET endpoint without changing its behavior.
sed 's/commons-codec:1.18.0/commons-codec:1.19.0/' "$repo/build.gradle" > "$sandbox/build.gradle"
cp "$sandbox/build.gradle" "$repo/build.gradle"
cat >> "$repo/build.gradle" <<'GRADLE'

// A service's existing tests can resolve a version different from production.
configurations.testRuntimeClasspath.resolutionStrategy.force 'commons-codec:commons-codec:1.18.0'
GRADLE
run_case PASS --console=plain
grep -q '"group":"commons-codec","artifact":"commons-codec","version":"1.19.0"' \
    "$repo/build/tmp/test/verifier-classpath.json"
echo 'PASS: dependency upgrade measured on the application version despite a conflicting test version' >&2

# A skipped test exits zero in Gradle. The script must still require actual comparison.
cp "$repo/build.gradle" "$sandbox/unskipped.gradle"
cat >> "$repo/build.gradle" <<'GRADLE'

tasks.named('test') {
    onlyIf { providers.gradleProperty('verify.mode').orNull != 'verify' }
}
GRADLE
run_case FAIL --console=plain
grep -q ':test SKIPPED' "$sandbox/stderr"
grep -q 'Verification test did not complete the comparison' "$sandbox/stderr"
cp "$sandbox/unskipped.gradle" "$repo/build.gradle"
echo 'PASS: skipped verification rejected despite Gradle success' >&2

# A real HTTP response change must fail even though it still returns valid JSON / HTTP 200.
source_file="$repo/src/test/java/upgrade/fixture/SampleApplication.java"
sed 's/new SampleDto("sample", 7/new SampleDto("changed", 7/' "$source_file" > "$sandbox/application.java"
cp "$sandbox/application.java" "$source_file"
run_case FAIL --console=plain
grep -q 'Fingerprint mismatch' "$sandbox/stderr" || {
    # Gradle's normal console abbreviates assertion messages; inspect its JUnit XML.
    grep -q 'Fingerprint mismatch' "$repo/build/test-results/test/TEST-upgrade.verifier.UpgradeConsistencyVerifierTest.xml"
}
echo 'PASS: changed runtime response rejected and worktree removed' >&2

# Baseline-stage failure must also yield exactly FAIL / 1 and clean the worktree.
run_case FAIL --console=plain -Pverify.get.paths=/does-not-exist
echo 'PASS: baseline failure rejected and worktree removed' >&2

# Failure before worktree creation follows the same output contract.
status=0
bash "$tool/verify-upgrade.sh" --repo "$sandbox/missing" >"$sandbox/stdout" 2>"$sandbox/stderr" || status=$?
[[ $status == 1 && $(cat "$sandbox/stdout") == FAIL && $(wc -l < "$sandbox/stdout") == 1 ]]
echo 'PASS: invalid repository returns FAIL / 1' >&2

# Repeat against a service submodule that already has a stale verifier committed.
git -C "$repo" restore --source=HEAD -- .
mkdir -p "$repo/backend"
mv "$repo/build.gradle" "$repo/upgrade-verifier.gradle" "$repo/src" "$repo/backend/"
printf "\ninclude 'backend'\n" >> "$repo/settings.gradle"
mkdir -p "$repo/backend/src/test/java/upgrade/verifier"
cat > "$repo/backend/src/test/java/upgrade/verifier/UpgradeConsistencyVerifierTest.java" <<'JAVA'
package upgrade.verifier;
public class UpgradeConsistencyVerifierTest {
    @org.junit.jupiter.api.Test
    void obsoleteVerifier() { throw new AssertionError("Stale verifier must be replaced"); }
}
JAVA
git -C "$repo" add .
git -C "$repo" -c user.name=Verifier -c user.email=verifier@example.test commit -qm multi-module
project_path=:backend
module_prefix=backend/
sed 's/commons-codec:1.18.0/commons-codec:1.19.0/' "$repo/backend/build.gradle" > "$sandbox/build.gradle"
cp "$sandbox/build.gradle" "$repo/backend/build.gradle"
run_case PASS --console=plain
echo 'PASS: service submodule selected and committed stale verifier replaced' >&2
