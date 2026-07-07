#!/bin/bash
# Bootstraps read-only kubectl access via the cloudflared Access tunnel
# described in remote-debugging.md. Idempotent across resume/clear/compact.
set -uo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Opt-in per environment: quietly no-op if remote debug isn't configured.
if [ -z "${K8S_API_HOSTNAME:-}" ] || [ -z "${CF_ACCESS_CLIENT_ID:-}" ] ||
   [ -z "${CF_ACCESS_CLIENT_SECRET:-}" ] || [ -z "${K8S_BEARER_TOKEN:-}" ]; then
  echo "session-start: remote-debug env vars not set, skipping cloudflared bootstrap" >&2
  exit 0
fi

# Keep in sync with the image tag in cluster/services/cloudflared.yaml.
CLOUDFLARED_VERSION="2024.12.2"
BIN_DIR="${HOME}/.local/bin"
mkdir -p "$BIN_DIR"
export PATH="${BIN_DIR}:${PATH}"
echo "export PATH=\"${BIN_DIR}:\$PATH\"" >> "$CLAUDE_ENV_FILE"

arch() {
  case "$(uname -m)" in
    x86_64) echo "amd64" ;;
    aarch64|arm64) echo "arm64" ;;
    *) echo "unsupported" ;;
  esac
}
ARCH="$(arch)"

# Downloads to a temp file and atomically mv's it into place (no partial
# binaries on failure); verifies sha256 against $3 if reachable, else warns
# and installs unverified rather than treating a missing checksum as fatal.
download_verified() {
  local url="$1" dest="$2" checksum_url="${3:-}" tmp expected actual
  tmp="$(mktemp "${dest}.XXXXXX")" || return 1
  if ! curl -fsSL -o "$tmp" "$url"; then
    rm -f "$tmp"
    return 1
  fi
  if [ -n "$checksum_url" ]; then
    if expected="$(curl -fsSL "$checksum_url" 2>/dev/null | awk '{print $1; exit}')" && [ -n "$expected" ]; then
      actual="$(sha256sum "$tmp" | awk '{print $1}')"
      if [ "$expected" != "$actual" ]; then
        echo "session-start: checksum mismatch for $(basename "$dest") (expected $expected, got $actual) — refusing to install" >&2
        rm -f "$tmp"
        return 1
      fi
    else
      echo "session-start: no checksum available at $checksum_url, installing $(basename "$dest") unverified" >&2
    fi
  fi
  chmod +x "$tmp"
  mv "$tmp" "$dest"
}

if ! command -v cloudflared >/dev/null 2>&1; then
  if [ "$ARCH" = "unsupported" ]; then
    echo "session-start: unsupported arch $(uname -m), skipping cloudflared install" >&2
  else
    CF_URL="https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-${ARCH}"
    download_verified "$CF_URL" "${BIN_DIR}/cloudflared" "${CF_URL}.sha256" \
      || echo "session-start: cloudflared install failed (check environment's Custom allowed domains for github.com/objects.githubusercontent.com)" >&2
  fi
fi

if ! command -v kubectl >/dev/null 2>&1; then
  if [ "$ARCH" = "unsupported" ]; then
    echo "session-start: unsupported arch $(uname -m), skipping kubectl install" >&2
  else
    KUBECTL_VERSION="$(curl -fsSL https://dl.k8s.io/release/stable.txt 2>/dev/null)"
    if [ -n "$KUBECTL_VERSION" ]; then
      KUBECTL_URL="https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${ARCH}/kubectl"
      download_verified "$KUBECTL_URL" "${BIN_DIR}/kubectl" "${KUBECTL_URL}.sha256" \
        || echo "session-start: kubectl install failed (check environment's Custom allowed domains for dl.k8s.io)" >&2
    else
      echo "session-start: could not resolve dl.k8s.io/release/stable.txt, skipping kubectl install" >&2
    fi
  fi
fi

# Reuse an already-running forwarder across resume/clear/compact.
PIDFILE="/tmp/cloudflared-access-tcp.pid"
LOGFILE="/tmp/cloudflared-access-tcp.log"
FORWARDER_UP=0
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  FORWARDER_UP=1
fi

if [ "$FORWARDER_UP" -eq 0 ] && command -v cloudflared >/dev/null 2>&1; then
  nohup cloudflared access tcp \
    --hostname "$K8S_API_HOSTNAME" \
    --url 127.0.0.1:6443 \
    --service-token-id "$CF_ACCESS_CLIENT_ID" \
    --service-token-secret "$CF_ACCESS_CLIENT_SECRET" \
    > "$LOGFILE" 2>&1 &
  echo $! > "$PIDFILE"

  # Non-fatal if this never comes up (e.g. tunnel hostname not allowlisted).
  UP=0
  for _ in $(seq 1 15); do
    if (exec 3<>"/dev/tcp/127.0.0.1/6443") 2>/dev/null; then
      exec 3<&- 3>&-
      UP=1
      break
    fi
    sleep 1
  done
  if [ "$UP" -eq 0 ]; then
    echo "session-start: cloudflared forwarder did not come up on 127.0.0.1:6443 within 15s — see $LOGFILE" >&2
  fi
fi

# Throwaway kubeconfig — regenerated every session, never committed.
KUBE_DIR="${HOME}/.kube"
mkdir -p "$KUBE_DIR"
KUBECONFIG_PATH="${KUBE_DIR}/config-remote-debug"
cat > "$KUBECONFIG_PATH" <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: homenet-remote-debug
    cluster:
      server: https://127.0.0.1:6443
      # TLS terminates at the real API server, not 127.0.0.1, so the SAN
      # won't match (see remote-debugging.md); the CF Access token + bearer
      # token below are the real auth boundary.
      insecure-skip-tls-verify: true
contexts:
  - name: homenet-remote-debug
    context:
      cluster: homenet-remote-debug
      user: homenet-remote-debug
current-context: homenet-remote-debug
users:
  - name: homenet-remote-debug
    user:
      token: "${K8S_BEARER_TOKEN}"
EOF
chmod 600 "$KUBECONFIG_PATH"

echo "export KUBECONFIG=${KUBECONFIG_PATH}" >> "$CLAUDE_ENV_FILE"
echo "session-start: remote-debug kubeconfig written to ${KUBECONFIG_PATH}" >&2
