# Docker Guide

The checked-in Compose example runs ZeroGravity v1.4.2 with one account and publishes the API at `http://127.0.0.1:8741`. The Dockerfile bundles the backend for Linux AMD64 and ARM64. Use Docker Engine 28 or later with the Compose and Buildx plugins. [Docker port publishing](https://docs.docker.com/engine/network/port-publishing/)

## Prepare the local configuration

From the repository root, place your existing authorized account file at `./accounts.json`. The `accounts` array must contain exactly one enabled account with an email and a refresh token. If present, `disabled` must be `false` and `alias` must be a string or null. If the file specifies an `active` account, use that same email. If it contains an `extracted_at` value, use its original RFC 3339 timestamp.

The startup check reads the source file through a read-only mount and creates a private copy on a dedicated in-memory filesystem. ZeroGravity v1.4.2 uses both metadata fields when loading the account. If either field is missing, the copy uses the sole email as `active` and the current UTC load time as `extracted_at`. The recorded load time applies only to the copy. Upgrades replace an empty placeholder left by the previous bind mount. If the config volume contains an actual `accounts.json` file, move it aside before starting the new profile.

Generate a new proxy API key with OpenSSL. This command creates `.env` with restricted permissions and preserves any existing file.

```bash
(
  umask 077
  set -C
  key=$(openssl rand -hex 32) &&
    printf 'ZEROGRAVITY_API_KEY=%s\n' "$key" > .env
)
chmod 600 .env accounts.json
```

For an existing `.env`, set `ZEROGRAVITY_API_KEY` to a single printable ASCII key without spaces or commas. Compose also accepts the key from your shell environment, which takes precedence over `.env`. Both local files are ignored by Git and excluded from the Docker build context. Keep them private and use `config --quiet` to validate the setup without displaying the key.

## Build and start

```bash
docker compose -f docker-compose.example.yml config --quiet
docker compose -f docker-compose.example.yml build
docker compose -f docker-compose.example.yml up -d --wait
curl -fsS http://127.0.0.1:8741/health
```

The example builds `zerogravity:v1.4.2-local` from the checked-in Dockerfile and runs that local image. Compose refuses a missing or empty API key. A startup check validates the key and the structure of the mounted account file before launching ZeroGravity. The `/health` route reports whether the proxy is running. Validate account refresh, model access, and streaming separately. See the [API authentication reference](api.md#api-key-protection) and the [Claude Code configuration](clients.md#claude-code).

The API key is available to users with Docker inspection access. Keep rendered Compose configurations and container inspection output private.

If Compose returns early during a restart, `docker compose -f docker-compose.example.yml ps` shows the current container state. With the proxy key exported, `python3 scripts/check_proxy.py status --wait-ready 90` measures recovery of the local API and managed account without sending a generation request. [Client diagnostics](clients.md#diagnosing-a-single-account-session)

## Test the newer backend

The default image pairs the v1.4.2 proxy with the 1.18.3 IDE language server. To build the optional 1.20.6 backend under its own local tag and check it with synthetic credentials, run these commands from the repository root. The smoke test requires Docker Compose 2.24.4 or later and `jq`. It runs with networking disabled, including during the restart check.

```sh
ZEROGRAVITY_BACKEND=1.20.6 docker compose -f docker-compose.example.yml build
sh tests/image-smoke.sh zerogravity:v1.4.2-1.20.6
```

The build verifies the architecture-specific SHA-256 for the Google package, proxy, CLI and shared library. To select the candidate for subsequent Compose commands, set `ZEROGRAVITY_BACKEND=1.20.6` in the deployment's `.env` and recreate the service. Remove that setting and recreate the service to return to the default image. For tested versions and image digests, see the [fork audit](analysis.md#výsledek-úprav-ve-forku).

## Request Queue

The Compose example sets `ZEROGRAVITY_QUOTA_CAP=0` to disable quota-triggered account rotation. It enables the request queue and sets these limits for one account.

| Variable | Compose value | Behavior |
| --- | --- | --- |
| `ZEROGRAVITY_QUEUE_ENABLED` | `true` | Enable queueing |
| `ZEROGRAVITY_QUEUE_CONCURRENCY` | `1` | Maximum concurrent generation requests |
| `ZEROGRAVITY_QUEUE_INTERVAL_MS` | `500` | Minimum interval between dispatches in milliseconds |
| `ZEROGRAVITY_QUEUE_TIMEOUT_MS` | `30000` | Maximum queue wait in milliseconds before HTTP 408 |
| `ZEROGRAVITY_QUEUE_MAX_SIZE` | `4` | Maximum queue depth before HTTP 503 |

Queue wait is distinct from the time to the first response event and the idle timeout during a stream. The default stream idle timeout is 120 seconds and can be set with `ZEROGRAVITY_STREAM_IDLE_TIMEOUT_SECS`.

## Updating

Rebuild whenever you change the checked-in Dockerfile. Record the built image ID when reporting a result with `docker image inspect zerogravity:v1.4.2-local --format '{{.Id}}'`.

```bash
docker compose -f docker-compose.example.yml build
docker compose -f docker-compose.example.yml up -d --wait
```

If you replace the bind-mounted account file, recreate the container to load the replacement.

```bash
docker compose -f docker-compose.example.yml up -d --force-recreate --wait
```
