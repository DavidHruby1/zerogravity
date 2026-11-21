#!/bin/sh
set -eu

repo_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT
trap 'exit 1' HUP INT TERM

mkdir "$work_dir/bin" "$work_dir/source" "$work_dir/runtime" "$work_dir/config"
cat > "$work_dir/bin/zerogravity" <<'SH'
#!/bin/sh
printf 'launched %s\n' "$@"
SH
chmod +x "$work_dir/bin/zerogravity"

export PATH="$work_dir/bin:$PATH"
export ZEROGRAVITY_CONFIG_DIR="$work_dir/config"
export ZEROGRAVITY_ACCOUNTS_SOURCE_DIR="$work_dir/source"
export ZEROGRAVITY_ACCOUNTS_RUNTIME_DIR="$work_dir/runtime"
fixture="$ZEROGRAVITY_ACCOUNTS_SOURCE_DIR/accounts.json"
config_file="$ZEROGRAVITY_CONFIG_DIR/accounts.json"
runtime_accounts="$ZEROGRAVITY_ACCOUNTS_RUNTIME_DIR/accounts.json"
launcher="$repo_dir/scripts/start-local.sh"
key_error='Set one nonempty ZEROGRAVITY_API_KEY using printable ASCII without spaces or commas.'
account_error='accounts.json must contain one enabled account with a valid email and refresh token. Check any alias, active email, and extraction timestamp.'

assert_rejected() {
    if output=$(sh "$launcher" --headless 2>&1) || [ "$output" != "$2" ]; then
        printf 'FAIL: %s\n' "$1" >&2
        exit 1
    fi
}

check_account() {
    printf '%s\n' "$2" > "$fixture"
    assert_rejected "$1" "$account_error"
}

assert_launched() {
    if ! output=$(sh "$launcher" --headless 2>&1) || [ "$output" != 'launched --headless' ]; then
        printf 'FAIL: %s\n' "$1" >&2
        exit 1
    fi
}

read_normalized_metadata() (
    cd "$ZEROGRAVITY_ACCOUNTS_RUNTIME_DIR"
    sqlite3 -batch -bail -init /dev/null ':memory:' "
        SELECT json_extract(CAST(readfile('accounts.json') AS TEXT), '$.active'),
               json_extract(CAST(readfile('accounts.json') AS TEXT), '$.accounts[0].extracted_at');"
)

unset ZEROGRAVITY_API_KEY
assert_rejected 'missing API key' "$key_error"
export ZEROGRAVITY_API_KEY=''
assert_rejected 'empty API key' "$key_error"
export ZEROGRAVITY_API_KEY='   '
assert_rejected 'blank API key' "$key_error"
export ZEROGRAVITY_API_KEY='test key'
assert_rejected 'API key containing whitespace' "$key_error"
export ZEROGRAVITY_API_KEY='test-key,other-key'
assert_rejected 'multiple API keys' "$key_error"
export ZEROGRAVITY_API_KEY='test-kéy'
assert_rejected 'non-ASCII API key' "$key_error"

export ZEROGRAVITY_API_KEY='synthetic-test-key'
assert_rejected 'missing account file' "$account_error"
mkdir "$fixture"
assert_rejected 'account file is a directory' "$account_error"
rmdir "$fixture"

check_account 'invalid JSON' '{'
check_account 'wrong top-level type' '[]'
check_account 'wrong accounts type' '{"accounts":{}}'
check_account 'zero accounts' '{"accounts":[]}'
check_account 'multiple accounts' '{"accounts":[{"email":"one@example.invalid","refresh_token":"synthetic-token"},{"email":"two@example.invalid","refresh_token":"synthetic-token"}]}'
check_account 'duplicate accounts field' '{"accounts":[{"email":"one@example.invalid","refresh_token":"synthetic-token"}],"accounts":[]}'
check_account 'wrong account type' '{"accounts":["account"]}'
check_account 'missing email' '{"accounts":[{"refresh_token":"synthetic-token"}]}'
check_account 'wrong email type' '{"accounts":[{"email":5,"refresh_token":"synthetic-token"}]}'
check_account 'invalid email' '{"accounts":[{"email":"user ","refresh_token":"synthetic-token"}]}'
check_account 'missing refresh token' '{"accounts":[{"email":"user@example.invalid"}]}'
check_account 'wrong refresh token type' '{"accounts":[{"email":"user@example.invalid","refresh_token":false}]}'
check_account 'blank refresh token' '{"accounts":[{"email":"user@example.invalid","refresh_token":" \t"}]}'
check_account 'refresh token containing a null character' '{"accounts":[{"email":"user@example.invalid","refresh_token":"synthetic\u0000token"}]}'
check_account 'duplicate refresh token field' '{"accounts":[{"email":"user@example.invalid","refresh_token":"synthetic-token","refresh_token":""}]}'
check_account 'wrong alias type' '{"accounts":[{"email":"user@example.invalid","refresh_token":"synthetic-token","alias":true}]}'
check_account 'duplicate alias field' '{"accounts":[{"email":"user@example.invalid","refresh_token":"synthetic-token","alias":"label","alias":null}]}'
check_account 'sole account is disabled' '{"accounts":[{"email":"user@example.invalid","refresh_token":"synthetic-token","disabled":true}]}'
check_account 'wrong disabled type' '{"accounts":[{"email":"user@example.invalid","refresh_token":"synthetic-token","disabled":7}]}'
check_account 'duplicate disabled field' '{"accounts":[{"email":"user@example.invalid","refresh_token":"synthetic-token","disabled":false,"disabled":true}]}'
check_account 'active email differs from the sole account email' '{"accounts":[{"email":"user@example.invalid","refresh_token":"synthetic-token"}],"active":"other@example.invalid"}'
check_account 'wrong active type' '{"accounts":[{"email":"user@example.invalid","refresh_token":"synthetic-token"}],"active":true}'
check_account 'duplicate active field' '{"accounts":[{"email":"user@example.invalid","refresh_token":"synthetic-token"}],"active":"user@example.invalid","active":null}'
check_account 'wrong extraction timestamp type' '{"accounts":[{"email":"user@example.invalid","refresh_token":"synthetic-token","extracted_at":5}]}'
check_account 'malformed extraction timestamp' '{"accounts":[{"email":"user@example.invalid","refresh_token":"synthetic-token","extracted_at":"2026-02-21"}]}'
check_account 'duplicate extraction timestamp' '{"accounts":[{"email":"user@example.invalid","refresh_token":"synthetic-token","extracted_at":"2026-02-21T05:08:32Z","extracted_at":null}]}'

timestamp='2026-02-21T05:08:32.123456+00:00'
printf '{"accounts":[{"email":"user+label@example.invalid","refresh_token":"synthetic-token","alias":"label","disabled":false,"extracted_at":"%s"}],"active":"user+label@example.invalid"}\n' "$timestamp" > "$fixture"
assert_launched 'valid config passes its command arguments to the proxy'
if [ "$(read_normalized_metadata)" != "user+label@example.invalid|$timestamp" ]; then
    echo 'FAIL: supplied active account and extraction timestamp are preserved' >&2
    exit 1
fi
if [ "$(readlink -- "$config_file")" != "$runtime_accounts" ] || [ "$(stat -c '%a' -- "$runtime_accounts")" != '600' ]; then
    echo 'FAIL: account file is linked to the private runtime copy' >&2
    exit 1
fi

printf '%s\n' '{"accounts":[{"email":"user@example.invalid","refresh_token":"synthetic-token"}]}' > "$fixture"
cp "$fixture" "$work_dir/original.json"
printf 'preserve this config\n' > "$ZEROGRAVITY_CONFIG_DIR/usage.json"
unlink "$runtime_accounts"
assert_launched 'trimmed account file is normalized on restart'
case "$(read_normalized_metadata)" in
    user@example.invalid\|????-??-??T??:??:??Z) ;;
    *) echo 'FAIL: missing active account and UTC load time are filled in' >&2; exit 1 ;;
esac
if ! cmp -s "$fixture" "$work_dir/original.json" || [ "$(cat "$ZEROGRAVITY_CONFIG_DIR/usage.json")" != 'preserve this config' ]; then
    echo 'FAIL: startup leaves the source and other persistent config intact' >&2
    exit 1
fi

unlink "$config_file"
(umask 022; : > "$config_file")
assert_launched 'empty config placeholder from the previous bind mount is replaced'
if [ "$(readlink -- "$config_file")" != "$runtime_accounts" ]; then
    echo 'FAIL: placeholder was replaced with the canonical account link' >&2
    exit 1
fi

printf '{"accounts":[{"email":"user@example.invalid","refresh_token":"synthetic-token","alias":null,"extracted_at":"%s"}]}\n' "$timestamp" > "$fixture"
assert_launched 'active account is filled independently of supplied extraction time'
if [ "$(read_normalized_metadata)" != "user@example.invalid|$timestamp" ]; then
    echo 'FAIL: extraction timestamp survives when active is filled' >&2
    exit 1
fi

unlink "$config_file"
printf 'preserve this file\n' > "$config_file"
assert_rejected 'existing unrelated account file' 'The proxy config directory has an existing accounts.json file. Move it aside before starting this profile.'
if [ "$(cat "$config_file")" != 'preserve this file' ]; then
    echo 'FAIL: an existing config file was overwritten' >&2
    exit 1
fi
mv -- "$config_file" "$work_dir/unrelated.json"
ln -s -- "$work_dir/unrelated.json" "$config_file"
assert_rejected 'existing unrelated account symlink' 'The proxy config directory has an existing accounts.json link with a different target.'
if [ "$(readlink -- "$config_file")" != "$work_dir/unrelated.json" ] || [ "$(cat "$work_dir/unrelated.json")" != 'preserve this file' ]; then
    echo 'FAIL: an unrelated symlink was modified' >&2
    exit 1
fi

echo 'Startup preflight checks passed.'
