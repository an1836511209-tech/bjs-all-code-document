#!/usr/bin/env sh
set -eu
environment=${1:-}
case "$environment" in test|uat) ;; *) echo 'Usage: sh scripts/start-nonprod.sh test|uat [export-scenario]' >&2; exit 2 ;; esac
repo_path=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_path"
runtime_path="$repo_path/deploy/environments/$environment/runtime.env"
test -f "$runtime_path" || { echo 'Missing non-production runtime.env' >&2; exit 2; }
configured=$(sed -n 's/^[[:space:]]*APP_ENV[[:space:]]*=[[:space:]]*//p' "$runtime_path" | tail -n 1 | tr -d "\"'[:space:]")
test -z "$configured" || test "$configured" = "$environment" || { echo 'runtime.env APP_ENV does not match selected environment' >&2; exit 2; }
export APP_ENV="$environment" BJS_ENV_FILE="$runtime_path"
export DMP_MOCK_EXPORT_SCENARIO="${2:-normal}"
if test "$environment" = test; then default_subnet=10.201.0.0/24; else default_subnet=10.202.0.0/24; fi
export BJS_DOCKER_SUBNET="${BJS_DOCKER_SUBNET:-$default_subnet}"
exec docker compose --project-name "bjs-$environment" --env-file "$runtime_path" \
  -f compose.yaml -f compose.dmp-mock.yaml --profile dmp-mock up -d --build
