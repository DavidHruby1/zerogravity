#!/bin/sh
# Exercise the Compose entry point in an isolated project with no external network.
set -eu

repo=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
fixture=$(mktemp -d)
project="zg-smoke-$(basename "$fixture" | tr '[:upper:].' '[:lower:]-')"
export ZG_SMOKE_IMAGE=${1:-zerogravity:v1.4.2-local}
export ZEROGRAVITY_API_KEY=synthetic-smoke-key
compose() {
    docker compose -p "$project" --env-file /dev/null \
        -f "$fixture/compose.yml" -f "$fixture/isolated.yml" "$@"
}
cleanup() {
    status=$?
    if [ "$status" -ne 0 ]; then
        compose logs --no-color >&2 || :
    fi
    compose down --volumes >/dev/null || {
        down_status=$?
        if [ "$status" -eq 0 ]; then
            status=$down_status
        fi
    }
    rm -rf "$fixture"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

mkdir "$fixture/scripts"
cp "$repo/docker-compose.example.yml" "$fixture/compose.yml"
cp "$repo/scripts/start-local.sh" "$fixture/scripts/"
cat > "$fixture/isolated.yml" <<'YAML'
services:
  zerogravity:
    image: "${ZG_SMOKE_IMAGE}"
    network_mode: none
    ports: !reset []
YAML
printf '%s\n' '{"accounts":[{"email":"smoke@example.invalid","refresh_token":"1//synthetic-smoke-token"}]}' > "$fixture/accounts.json"
cp "$fixture/accounts.json" "$fixture/original-accounts.json"

wait_for_service() {
    phase=$1
    started=$(date +%s)
    deadline=$((started + 90))
    while :; do
        snapshot=$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}} {{.RestartCount}} {{.State.ExitCode}}' "$container") || return "$?"
        read -r state health restarts exit_code <<EOF
$snapshot
EOF
        now=$(date +%s)
        elapsed=$((now - started))
        case "$state:$health" in
            running:healthy)
                printf '%s healthy after %ss (%s automatic restarts)\n' "$phase" "$elapsed" "$restarts"
                return 0
                ;;
            created:*|running:starting|running:unhealthy|restarting:*|exited:*)
                if [ "$now" -lt "$deadline" ]; then
                    sleep 1
                    continue
                fi
                ;;
        esac
        printf '%s did not become healthy after %ss (state=%s, health=%s, automatic restarts=%s, container exit=%s)\n' \
            "$phase" "$elapsed" "$state" "$health" "$restarts" "$exit_code" >&2
        if [ "$exit_code" -ne 0 ]; then
            return "$exit_code"
        fi
        return 1
    done
}

compose up --no-build --pull never -d
container=$(compose ps --all --quiet zerogravity)
wait_for_service 'Initial startup'
compose exec -T zerogravity pgrep -x language_server >/dev/null
api() {
    compose exec -T zerogravity curl --silent --show-error --max-time 5 "$@"
}
url=http://127.0.0.1:8741
test "$(api --output /dev/null --write-out '%{http_code}' "$url/v1/models")" = 401
api --fail -H "x-api-key: $ZEROGRAVITY_API_KEY" "$url/v1/models" |
    jq -e 'any(.data[]; .id == "sonnet-4.6")' >/dev/null
check_account() {
    api --fail -H "x-api-key: $ZEROGRAVITY_API_KEY" "$url/v1/accounts" |
        jq -e '.accounts | length == 1 and .[0].active and .[0].email == "smoke@example.invalid"' >/dev/null
    api --fail -H "x-api-key: $ZEROGRAVITY_API_KEY" "$url/v1/accounts/status" |
        jq -e '.active_index == 0 and .accounts[0].state == "active"' >/dev/null
}
check_account
# A listed synthetic account cannot obtain an OAuth token on this network.
status=$(api -o /tmp/zg-smoke-error.json -w '%{http_code}' -H "x-api-key: $ZEROGRAVITY_API_KEY" \
    -H 'Content-Type: application/json' -H 'anthropic-version: 2023-06-01' \
    -d '{"model":"sonnet-4.6","max_tokens":16,"messages":[{"role":"user","content":"fixture"}],"stream":true}' \
    "$url/v1/messages")
test "$status" = 401
compose exec -T zerogravity cat /tmp/zg-smoke-error.json |
    jq -e '.error.type == "authentication_error" and (.error.message | contains("No OAuth token"))' >/dev/null
compose restart
wait_for_service 'After Compose restart'
compose exec -T zerogravity pgrep -x language_server >/dev/null
check_account
cmp "$fixture/accounts.json" "$fixture/original-accounts.json"
docker image inspect "$ZG_SMOKE_IMAGE" --format 'Verified local API and managed account on {{.Os}}/{{.Architecture}} {{.Id}}'
