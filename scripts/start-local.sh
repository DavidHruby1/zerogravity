#!/bin/sh
set -eu

# Accept one key with ASCII characters from ! through ~, excluding commas.
case "${ZEROGRAVITY_API_KEY:-}" in
    ''|*[!!-~]*|*,*)
        echo 'Set one nonempty ZEROGRAVITY_API_KEY using printable ASCII without spaces or commas.' >&2
        exit 1
        ;;
esac

source_dir=${ZEROGRAVITY_ACCOUNTS_SOURCE_DIR:-/run/secrets/zerogravity}
runtime_dir=${ZEROGRAVITY_ACCOUNTS_RUNTIME_DIR:-/run/zerogravity}
config_dir=${ZEROGRAVITY_CONFIG_DIR:-/root/.config/zerogravity}
config_file="$config_dir/accounts.json"
runtime_accounts="$runtime_dir/accounts.json"

runtime_file=$(umask 077; mktemp "$runtime_dir/.accounts.XXXXXX")
link_dir=''
cleanup() {
    rm -f -- "$runtime_file"
    if [ -n "$link_dir" ]; then
        rm -f -- "$link_dir/accounts.json"
        rmdir -- "$link_dir"
    fi
}

trap cleanup EXIT
trap 'exit 1' HUP INT TERM

if ! (
    cd "$source_dir" &&
        [ -f accounts.json ] &&
        sqlite3 -batch -bail -init /dev/null ':memory:' <<'SQL'
WITH config AS (
    SELECT CAST(readfile('accounts.json') AS TEXT) AS document
), account AS (
    SELECT document,
           json_extract(document, '$.accounts[0].email') AS email,
           json_extract(document, '$.accounts[0].refresh_token') AS refresh_token,
           json_extract(document, '$.accounts[0].extracted_at') AS extracted_at,
           json_extract(document, '$.active') AS active
    FROM config
    WHERE CASE
        WHEN json_valid(document) IS NOT 1 OR instr(document, char(0)) > 0 THEN 0
        WHEN json_type(document) IS NOT 'object' THEN 0
        WHEN json_type(document, '$.accounts') IS NOT 'array' THEN 0
        WHEN json_array_length(document, '$.accounts') <> 1 THEN 0
        WHEN (SELECT count(*) FROM json_each(document) WHERE key = 'accounts') <> 1 THEN 0
        WHEN (SELECT count(*) FROM json_each(document) WHERE key = 'active') > 1 THEN 0
        WHEN json_type(document, '$.accounts[0]') IS NOT 'object' THEN 0
        WHEN json_type(document, '$.accounts[0].email') IS NOT 'text' THEN 0
        WHEN json_type(document, '$.accounts[0].refresh_token') IS NOT 'text' THEN 0
        WHEN coalesce(json_type(document, '$.accounts[0].alias'), 'null') NOT IN ('text', 'null') THEN 0
        WHEN coalesce(json_type(document, '$.accounts[0].disabled'), 'false') IS NOT 'false' THEN 0
        WHEN coalesce(json_type(document, '$.accounts[0].extracted_at'), 'null') NOT IN ('text', 'null') THEN 0
        WHEN EXISTS (
            SELECT 1 FROM json_each(document, '$.accounts[0]')
            WHERE key IN ('email', 'refresh_token', 'alias', 'disabled', 'extracted_at')
            GROUP BY key HAVING count(*) > 1
        ) THEN 0
        ELSE 1
    END
)
SELECT json_set(
    document,
    '$.active', coalesce(active, email),
    '$.accounts[0].extracted_at', coalesce(extracted_at, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
FROM account
WHERE email GLOB '?*@?*'
  AND length(email) - length(replace(email, '@', '')) = 1
  AND email NOT GLOB '*[^!-~]*'
  AND instr(email, char(0)) = 0
  AND refresh_token GLOB '?*'
  AND refresh_token NOT GLOB '*[^!-~]*'
  AND instr(refresh_token, char(0)) = 0
  AND (active IS NULL OR active = email)
  AND (extracted_at IS NULL OR (
      (extracted_at GLOB '????-??-??T??:??:??*Z' OR extracted_at GLOB '????-??-??T??:??:??*[+-]??:??')
      AND instr(extracted_at, char(0)) = 0
      AND datetime(extracted_at) IS NOT NULL
  ));
SQL
) > "$runtime_file" 2>/dev/null || [ ! -s "$runtime_file" ]; then
    echo 'accounts.json must contain one enabled account with a valid email and refresh token. Check any alias, active email, and extraction timestamp.' >&2
    exit 1
fi

if [ -L "$config_file" ]; then
    if [ "$(readlink -- "$config_file")" != "$runtime_accounts" ]; then
        echo 'The proxy config directory has an existing accounts.json link with a different target.' >&2
        exit 1
    fi
elif [ -f "$config_file" ] && [ ! -s "$config_file" ]; then
    # Docker can leave an empty placeholder from the previous bind mount.
    link_dir=$(mktemp -d "$config_dir/.account-link.XXXXXX")
    ln -sT -- "$runtime_accounts" "$link_dir/accounts.json"
    mv -T -- "$link_dir/accounts.json" "$config_file"
elif [ -e "$config_file" ]; then
    echo 'The proxy config directory has an existing accounts.json file. Move it aside before starting this profile.' >&2
    exit 1
else
    ln -sT -- "$runtime_accounts" "$config_file"
fi

mv -T -- "$runtime_file" "$runtime_accounts"
cleanup
trap - EXIT HUP INT TERM
exec zerogravity "$@"
