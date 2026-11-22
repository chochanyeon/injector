#!/bin/sh
set -eu

root=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
workspace=$(mktemp -d)
trap 'rm -rf -- "$workspace"' EXIT
project="$workspace/Injector workspace"
mkdir -p "$project/.venv/bin"
cp -p "$root/Start-Injector.command" "$project/"
cat > "$project/.venv/bin/python" <<'EOF'
#!/bin/sh
test "${PWD##*/}" = 'Injector workspace' &&
  test "$#" -eq 3 &&
  test "$1" = 'injector.py' &&
  test "$2" = 'serve' &&
  test "$3" = '--open'
EOF
chmod +x "$project/.venv/bin/python"
"$project/Start-Injector.command"
