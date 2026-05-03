#!/bin/bash
# Lambda entrypoint wrapper: starts Tailscale in userspace-networking mode,
# then hands off to the standard Lambda runtime (/lambda-entrypoint.sh).
#
# Auth key resolution (first match wins):
#   1. TAILSCALE_AUTH_KEY env var         — literal key (testing only)
#   2. TAILSCALE_API_KEY_SSM_PATH         — SSM path to a Tailscale personal API
#                                           key; the Lambda calls the Tailscale API
#                                           to mint a fresh single-use ephemeral key
#                                           on every cold start — no key rotation needed
#   3. TAILSCALE_AUTH_KEY_SSM_PATH        — SSM path to a static auth key (deprecated)
#
# If none is set the Lambda starts normally without Tailscale.

set -euo pipefail

TS_DIR="/tmp/tailscale"
TS_SOCK="${TS_DIR}/tailscaled.sock"
TS_LOG="${TS_DIR}/tailscaled.log"

# --------------------------------------------------------------------------- #
# Resolve auth key
# --------------------------------------------------------------------------- #

if [ -z "${TAILSCALE_AUTH_KEY:-}" ] && [ -n "${TAILSCALE_API_KEY_SSM_PATH:-}" ]; then
    echo "[tailscale] generating ephemeral auth key via Tailscale API"
    TAILSCALE_AUTH_KEY=$(python3 - <<'PYEOF'
import urllib.request, urllib.parse, json, os, sys, boto3

region  = os.environ.get("AWS_REGION", "ap-southeast-2")
ssm_path = os.environ.get("TAILSCALE_API_KEY_SSM_PATH", "")

try:
    ssm = boto3.client("ssm", region_name=region)
    api_key = ssm.get_parameter(Name=ssm_path, WithDecryption=True)["Parameter"]["Value"]

    payload = json.dumps({
        "capabilities": {
            "devices": {
                "create": {
                    "reusable":      False,
                    "ephemeral":     True,
                    "preauthorized": True,
                    "tags":          ["tag:voxhelm"],
                }
            }
        },
        "expirySeconds": 300,
        "description":   "orchestrator-lambda-ephemeral",
    }).encode()

    req = urllib.request.Request(
        "https://api.tailscale.com/api/v2/tailnet/-/keys",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        print(json.loads(r.read())["key"], end="")

except Exception as exc:
    print(f"[tailscale] WARNING: could not generate auth key: {exc}", file=sys.stderr)
PYEOF
    ) || true
fi

# Deprecated fallback: static auth key stored directly in SSM
if [ -z "${TAILSCALE_AUTH_KEY:-}" ] && [ -n "${TAILSCALE_AUTH_KEY_SSM_PATH:-}" ]; then
    echo "[tailscale] WARNING: TAILSCALE_AUTH_KEY_SSM_PATH is deprecated; use TAILSCALE_API_KEY_SSM_PATH"
    echo "[tailscale] fetching static auth key from SSM: ${TAILSCALE_AUTH_KEY_SSM_PATH}"
    TAILSCALE_AUTH_KEY=$(python3 - <<'PYEOF'
import boto3, os, sys
region = os.environ.get("AWS_REGION", "ap-southeast-2")
path   = os.environ.get("TAILSCALE_AUTH_KEY_SSM_PATH", "")
try:
    ssm = boto3.client("ssm", region_name=region)
    print(ssm.get_parameter(Name=path, WithDecryption=True)["Parameter"]["Value"], end="")
except Exception as exc:
    print(f"[tailscale] WARNING: SSM fetch failed: {exc}", file=sys.stderr)
PYEOF
    ) || true
fi

if [ -z "${TAILSCALE_AUTH_KEY:-}" ]; then
    echo "[tailscale] no auth key configured — skipping Tailscale setup"
    exec /lambda-entrypoint.sh "$@"
fi

# --------------------------------------------------------------------------- #
# Start tailscaled (userspace networking — no kernel TUN module required)
# --------------------------------------------------------------------------- #

mkdir -p "${TS_DIR}"

echo "[tailscale] starting tailscaled (userspace networking)"
tailscaled \
    --tun=userspace-networking \
    --state="${TS_DIR}/tailscaled.state" \
    --socket="${TS_SOCK}" \
    >> "${TS_LOG}" 2>&1 &

TAILSCALED_PID=$!

# Wait up to 3 s for the Unix socket to appear (6 × 0.5 s)
for i in $(seq 1 6); do
    [ -S "${TS_SOCK}" ] && break
    sleep 0.5
done

if [ ! -S "${TS_SOCK}" ]; then
    echo "[tailscale] WARNING: tailscaled did not start in time — continuing without Tailscale"
    kill "${TAILSCALED_PID}" 2>/dev/null || true
    exec /lambda-entrypoint.sh "$@"
fi

# --------------------------------------------------------------------------- #
# Connect to tailnet
# --------------------------------------------------------------------------- #

# Sanitize: underscores are not valid in DNS labels; truncate to 63 chars
HOSTNAME="orchestrator-lambda-${AWS_LAMBDA_FUNCTION_NAME:-unknown}"
HOSTNAME=$(echo "$HOSTNAME" | tr '_' '-' | cut -c 1-63)
echo "[tailscale] connecting as ${HOSTNAME}"

tailscale \
    --socket="${TS_SOCK}" \
    up \
    --authkey="${TAILSCALE_AUTH_KEY}" \
    --hostname="${HOSTNAME}" \
    --accept-routes \
    --accept-dns=false \
    --timeout=10s \
    && echo "[tailscale] connected to tailnet" \
    || echo "[tailscale] WARNING: tailscale up failed — Lambda will start without Tailscale"

# --------------------------------------------------------------------------- #
# Hand off to Lambda runtime
# --------------------------------------------------------------------------- #

exec /lambda-entrypoint.sh "$@"
