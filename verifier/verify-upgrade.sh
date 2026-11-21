#!/usr/bin/env bash
# stdout is a machine-readable verdict; Gradle and diagnostics go to stderr.
set -Eeuo pipefail

tool_home=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo=$PWD
project=:
scratch=
worktree_added=0
gradle_args=()

cleanup() {
    result=$?
    trap - EXIT INT TERM
    if [[ $worktree_added == 1 ]]; then
        git -C "$repo" worktree remove --force "$scratch/head" >&2 || result=1
    fi
    if [[ -n $scratch && $scratch == /tmp/upgrade-verifier.* ]]; then
        rm -rf -- "$scratch" || result=1
    fi
    if [[ $result == 0 ]]; then printf 'PASS\n'; exit 0; fi
    printf 'FAIL\n'
    exit 1
}
trap cleanup EXIT
trap 'exit 1' INT TERM

while (($#)); do
    case "$1" in
        --repo) repo=${2:?--repo requires a path}; shift 2 ;;
        --project) project=${2:?--project requires a Gradle project path}; shift 2 ;;
        --) shift; gradle_args=("$@"); break ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; exit 1 ;;
    esac
done

repo=$(git -C "$repo" rev-parse --show-toplevel)
baseline_commit=$(git -C "$repo" rev-parse --verify HEAD)
[[ -f $repo/gradlew ]] || { echo 'Target repository needs ./gradlew' >&2; exit 1; }
scratch=$(mktemp -d /tmp/upgrade-verifier.XXXXXXXX)
mkdir -p "$scratch/tool/src/test/java/upgrade"
cp -R "$tool_home/src/test/java/upgrade/verifier" "$scratch/tool/src/test/java/upgrade/"
cp "$tool_home/upgrade-verifier.gradle" "$tool_home/upgrade-verifier.init.gradle" "$scratch/tool/"
git -C "$repo" worktree add --detach "$scratch/head" "$baseline_commit" >&2
worktree_added=1

task="${project%:}:test"
run_verifier() {
    local directory=$1 mode=$2
    (
        cd -- "$directory"
        bash ./gradlew "$task" --tests '*UpgradeConsistencyVerifierTest' \
            --no-configuration-cache --no-build-cache --rerun-tasks \
            -I "$scratch/tool/upgrade-verifier.init.gradle" \
            "${gradle_args[@]}" \
            "-Pverify.project=$project" "-Pverify.tool.home=$scratch/tool" \
            "-Pverify.receipt.path=$scratch/verified" \
            "-Pverify.mode=$mode" "-Pbaseline.path=$scratch/baseline.json"
    ) >&2
}

run_verifier "$scratch/head" record
[[ -s $scratch/baseline.json ]] || { echo 'Baseline was not generated' >&2; exit 1; }
run_verifier "$repo" verify
[[ -s $scratch/verified && $(cat "$scratch/verified") == verified ]] || {
    echo 'Verification test did not complete the comparison' >&2
    exit 1
}
