#!/bin/bash
# Lambda entrypoint wrapper: starts Tailscale in userspace-networking mode,
# then hands off to the standard Lambda runtime (/lambda-entrypoint.sh).
#
# Auth key resolution (first match wins):
#   1. TAILSCALE_AUTH_KEY env var  — literal key (dev/testing only)
#   2. TAILSCALE_AUTH_KEY_SSM_PATH — SSM SecureString path (production)
#
# If neither is set the Lambda starts normally without Tailscale.

set -euo pipefail

TS_DIR="/tmp/tailscale"
TS_SOCK="${TS_DIR}/tailscaled.sock"
TS_LOG="${TS_DIR}/tailscaled.log"

# --------------------------------------------------------------------------- #
# Resolve auth key
# --------------------------------------------------------------------------- #

if [ -z "${TAILSCALE_AUTH_KEY:-}" ] && [ -n "${TAILSCALE_AUTH_KEY_SSM_PATH:-}" ]; then
    echo "[tailscale] fetching auth key from SSM: ${TAILSCALE_AUTH_KEY_SSM_PATH}"
    TAILSCALE_AUTH_KEY=$(python3 - <<'PYEOF'
import boto3, os, sys
region = os.environ.get("AWS_REGION", "ap-southeast-2")
path = os.environ.get("TAILSCALE_AUTH_KEY_SSM_PATH", "")
try:
    ssm = boto3.client("ssm", region_name=region)
    r = ssm.get_parameter(Name=path, WithDecryption=True)
    print(r["Parameter"]["Value"], end="")
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

# Wait up to 15 s for the Unix socket to appear
for i in $(seq 1 30); do
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

HOSTNAME="orchestrator-lambda-${AWS_LAMBDA_FUNCTION_NAME:-unknown}"
echo "[tailscale] connecting as ${HOSTNAME}"

tailscale \
    --socket="${TS_SOCK}" \
    up \
    --authkey="${TAILSCALE_AUTH_KEY}" \
    --hostname="${HOSTNAME}" \
    --accept-routes \
    --accept-dns=false \
    --timeout=8s \
    && echo "[tailscale] connected to tailnet" \
    || echo "[tailscale] WARNING: tailscale up failed — Lambda will start without Tailscale"

# --------------------------------------------------------------------------- #
# Hand off to Lambda runtime
# --------------------------------------------------------------------------- #

exec /lambda-entrypoint.sh "$@"
