#!/bin/sh
# Run the native Claude Code client against a synthetic Messages API.
set -eu

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ] || [ ! -f "$1" ] || [ ! -x "$1" ]; then
    printf 'Usage: sh tests/claude-code.sh /path/to/native/claude [local-docker-image]\n' >&2
    exit 2
fi
repo=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
claude=$(readlink -f -- "$1")
image=${2:-zerogravity:v1.4.2-local}
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
trap 'exit 1' HUP INT TERM

CGO_ENABLED=0 GOOS=linux GOWORK=off GOPROXY=off GOTOOLCHAIN=local GOCACHE="${GOCACHE:-$fixture/go-cache}" \
    go build -o "$fixture/server" "$repo/tests/claude-code-fixture.go"

docker run --rm --interactive --pull never --network none --read-only \
    --tmpfs /tmp:rw,nosuid,nodev \
    --mount "type=bind,source=$fixture/server,target=/fixture-server,readonly" \
    --mount "type=bind,source=$claude,target=/usr/local/bin/claude,readonly" \
    --entrypoint /bin/sh "$image" -s <<'CONTAINER'
set -eu
cd /tmp
printf 'fixture-file-1\n' > probe1.txt
printf 'fixture-file-2\n' > probe2.txt
/usr/local/bin/claude --version

for mode in success denial stream-error truncated truncated-no-retries recovery; do
    mkdir "$mode" "$mode/home"
    /fixture-server "$mode" "$mode/url" >"$mode/requests" 2>"$mode/server-error" &
    server=$!
    trap 'kill "$server" 2>/dev/null || :' EXIT
    timeout 5 sh -c 'until [ -s "$1" ]; do sleep 0.1; done' sh "$mode/url"

    set --
    if [ "$mode" = truncated-no-retries ]; then
        set -- CLAUDE_CODE_MAX_RETRIES=0
    fi
    status=0
    env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="/tmp/$mode/home" \
        ANTHROPIC_BASE_URL="$(cat "$mode/url")" ANTHROPIC_AUTH_TOKEN=fixture-key \
        CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK=1 "$@" \
        timeout 60 /usr/local/bin/claude -p --model sonnet-4.6 --tools Read \
        --allowedTools Read --max-turns 4 --no-session-persistence \
        'Read /tmp/probe1.txt and /tmp/probe2.txt.' \
        </dev/null >"$mode/output" 2>&1 || status=$?
    kill "$server"
    wait "$server" 2>/dev/null || :
    trap - EXIT

    first='rounds=0 stream=true same_first_body=true'
    success='status=200 sse_events=6'
    continuations="rounds=1 stream=true same_first_body=false $success
rounds=2 stream=true same_first_body=false $success"
    case "$mode" in
        success)
            expected="$first $success
$continuations"
            expected_status=0
            expected_output='Both fixture files were read.'
            ;;
        denial)
            expected="$first status=403 sse_events=0"
            expected_status=1
            expected_output='403 This service has been disabled in this account for violation of Terms of Service.'
            ;;
        stream-error)
            expected="$first status=200 sse_events=4"
            expected_status=1
            expected_output='Fixture stream error.'
            ;;
        truncated)
            expected="$first status=200 sse_events=3
$first status=403 sse_events=0"
            expected_status=1
            expected_output='Fixture received another request after truncation.'
            ;;
        truncated-no-retries)
            expected="$first status=200 sse_events=3"
            expected_status=1
            expected_output='API Error'
            ;;
        recovery)
            unavailable="$first status=503 sse_events=0"
            expected="$unavailable
$unavailable
$first $success
$continuations"
            expected_status=0
            expected_output='Both fixture files were read.'
            ;;
    esac
    if [ "$status" -ne "$expected_status" ] ||
        [ "$(cat "$mode/requests")" != "$expected" ] ||
        ! grep -Fq "$expected_output" "$mode/output"; then
        printf 'FAIL %s (Claude Code exit %s)\n' "$mode" "$status" >&2
        cat "$mode/requests" "$mode/output" "$mode/server-error" >&2
        exit 1
    fi
    printf 'PASS %s (%s Messages requests)\n' "$mode" "$(wc -l < "$mode/requests" | tr -d ' ')"
done
CONTAINER
