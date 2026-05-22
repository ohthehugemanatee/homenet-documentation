#!/usr/bin/env bash
# =============================================================================
# Longhorn Sequential Upgrade: 1.5.3 → 1.10.2
# =============================================================================
# Upgrade path: 1.5.3 → 1.6.4 → 1.7.2 → 1.8.1 → 1.9.2 → 1.10.2
#
# Longhorn enforces single-minor-version upgrades starting v1.5.0.
# Rollback is only possible BEFORE engine upgrade completes at each step.
# Once engines are upgraded, data structures change — rollback requires backup restore.
#
# IMPORTANT: This script assumes kubectl-manifest based deployment.
# If you switched to Helm at some point, adjust the apply/rollback sections.
#
# Prerequisites:
#   - kubectl configured and pointing at your cluster
#   - All Longhorn volumes healthy and attached
#   - Recent backups of ALL volumes (non-negotiable)
#   - Sufficient disk space for replica rebuilds
#   - jq installed
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NAMESPACE="longhorn-system"
LOG_FILE="/tmp/longhorn-upgrade-$(date +%Y%m%d-%H%M%S).log"
DRY_RUN="${DRY_RUN:-false}"
SKIP_BACKUP_CHECK="${SKIP_BACKUP_CHECK:-false}"
AUTO_ENGINE_UPGRADE="${AUTO_ENGINE_UPGRADE:-true}"

# Target versions in order. Using latest stable patch for each minor.
# Verify these are still current before running.
UPGRADE_PATH=(
  "1.6.4"
  "1.7.2"
  "1.8.1"
  "1.9.2"
  "1.10.2"
)

# Timeouts
MANAGER_READY_TIMEOUT=900    # 5 min for manager pods
ENGINE_UPGRADE_TIMEOUT=600   # 10 min for engine upgrades
VOLUME_HEALTHY_TIMEOUT=900   # 15 min for volumes to become healthy
SETTLE_DELAY=30              # seconds to wait after upgrade before checks

# ---------------------------------------------------------------------------
# Breaking changes / pre-checks per version
# ---------------------------------------------------------------------------
declare -A VERSION_NOTES
VERSION_NOTES["1.6.4"]="
  BREAKING:
  - CSI snapshot CRDs must be v1 (v1beta1 removed in 1.6.1+)
  - Mandatory engine upgrade enforcement begins
  - backendStoreDriver param renamed to dataEngine in StorageClasses
  - Deprecated CR fields from 1.5 removed in 1.7 — clean up now
  - Linux kernel 5.15 may cause reboots on IO errors — need 5.19+
  PRE-CHECK:
  - Verify CSI snapshot CRDs are v1
  - Check kernel version >= 5.19
  - Verify no StorageClasses use backendStoreDriver param
"
VERSION_NOTES["1.7.2"]="
  BREAKING:
  - Environment check script deprecated (use Longhorn CLI instead)
  - Several CR fields deprecated in 1.6 are removed
  - Kubernetes >= 1.21 required
  PRE-CHECK:
  - Verify deprecated fields cleaned up from 1.6 upgrade
"
VERSION_NOTES["1.8.1"]="
  BREAKING:
  - Environment check script removed
  - Kubernetes >= 1.25 required (CSI external-snapshotter v8.2.0)
  - Default block size for block-type disks changed from 4096 to 512
  - V2 data engine corruption fix (if using V2)
  PRE-CHECK:
  - Verify Kubernetes version >= 1.25
"
VERSION_NOTES["1.9.2"]="
  BREAKING:
  - v1beta1 API deprecated, auto-migration to v1beta2 occurs during this upgrade
  - Deprecated fields signaled for removal
  - Kubernetes >= 1.25 required
  PRE-CHECK:
  - Verify Kubernetes version >= 1.25
  - After upgrade: verify all CRs migrated to v1beta2
"
VERSION_NOTES["1.10.2"]="
  BREAKING:
  - v1beta1 API version REMOVED entirely
  - replica.status.evictionRequested field removed
  - Must manually migrate CRD storedVersions from v1beta1 to v1beta2
    BEFORE this upgrade (critical if cluster predates v1.3.0 — yours does)
  PRE-CHECK:
  - Run CRD storage version migration script
  - Verify no v1beta1 in CRD storedVersions
"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log() {
  local level="$1"; shift
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $*"
  echo "$msg" | tee -a "$LOG_FILE"
}
info()  { log "INFO" "$@"; }
warn()  { log "WARN" "$@"; }
error() { log "ERROR" "$@"; }
fatal() { log "FATAL" "$@"; exit 1; }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
current_version() {
  kubectl -n "$NAMESPACE" get daemonset longhorn-manager \
    -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null \
    | grep -oP 'v?\K[0-9]+\.[0-9]+\.[0-9]+' || echo "unknown"
}

wait_for_pods_ready() {
  local timeout="$1"
  local start=$(date +%s)
  info "Waiting for all Longhorn pods to be ready (timeout: ${timeout}s)..."
  while true; do
    local not_ready
    # only count pods that are expected to be Running
    # (ignore Completed jobs, Terminating pods, Error from old jobs)
    not_ready=$(kubectl -n "$NAMESPACE" get pods --no-headers 2>/dev/null \
        | grep -v "Completed" \
        | grep -v "Error" \
        | grep -v "ContainerStatusUnknown" \
        | grep -v "Terminating" \
        | grep -cvE "Running\s" || true)

    # Also check that Running pods have all containers ready
    local unready_containers
    unready_containers=$(kubectl -n "$NAMESPACE" get pods --no-headers 2>/dev/null \
      | grep "Running" \
      | awk '{split($2,a,"/"); if(a[1]!=a[2]) print $1}' | wc -l)

    if [[ "$not_ready" -eq 0 && "$unready_containers" -eq 0 ]]; then
      info "All Longhorn pods ready."
      return 0
    fi
    local elapsed=$(( $(date +%s) - start ))
    if [[ "$elapsed" -ge "$timeout" ]]; then
      error "Timeout waiting for pods. Not ready: $not_ready, Unready containers: $unready_containers"
      kubectl -n "$NAMESPACE" get pods --no-headers | grep -v "Running" | tee -a "$LOG_FILE"
      return 1
    fi
    sleep 10
  done
}

wait_for_volumes_healthy() {
  local timeout="$1"
  local start=$(date +%s)
  info "Waiting for all volumes to be healthy (timeout: ${timeout}s)..."
  while true; do
    local unhealthy
    unhealthy=$(kubectl -n "$NAMESPACE" get volumes.longhorn.io -o json 2>/dev/null \
      | jq '[.items[] | select(.status.state == "attached" and .status.robustness != "healthy")] | length')
    local degraded
    degraded=$(kubectl -n "$NAMESPACE" get volumes.longhorn.io -o json 2>/dev/null \
      | jq '[.items[] | select(.status.robustness == "degraded")] | length')

    if [[ "$unhealthy" -eq 0 && "$degraded" -eq 0 ]]; then
      info "All attached volumes healthy."
      return 0
    fi
    local elapsed=$(( $(date +%s) - start ))
    if [[ "$elapsed" -ge "$timeout" ]]; then
      warn "Timeout: $unhealthy unhealthy, $degraded degraded volumes remain."
      kubectl -n "$NAMESPACE" get volumes.longhorn.io \
        -o custom-columns='NAME:.metadata.name,STATE:.status.state,ROBUSTNESS:.status.robustness' \
        | tee -a "$LOG_FILE"
      return 1
    fi
    sleep 15
  done
}

get_engine_image_for_version() {
  local version="$1"
  # The engine image name follows the pattern ei-<hash>, get it from running system
  kubectl -n "$NAMESPACE" get engineimages.longhorn.io -o json \
    | jq -r ".items[] | select(.spec.image | contains(\"v${version}\")) | .metadata.name" \
    | head -1
}

upgrade_engines() {
  local target_version="$1"
  info "Upgrading volume engines to v${target_version}..."

  local target_image
  target_image=$(kubectl -n "$NAMESPACE" get engineimages.longhorn.io -o json \
    | jq -r ".items[] | select(.spec.image | contains(\"v${target_version}\")) | .spec.image" \
    | head -1)

  if [[ -z "$target_image" ]]; then
    warn "No engine image found for v${target_version}. Engine upgrade may happen automatically."
    return 0
  fi

  info "Target engine image: $target_image"

  # Get all volumes that need engine upgrade
  local volumes
  volumes=$(kubectl -n "$NAMESPACE" get volumes.longhorn.io -o json \
    | jq -r ".items[] | select(.spec.engineImage != \"$target_image\") | .metadata.name")

  if [[ -z "$volumes" ]]; then
    info "All volumes already on target engine image."
    return 0
  fi

  for vol in $volumes; do
    info "  Upgrading engine for volume: $vol"
    if [[ "$DRY_RUN" == "false" ]]; then
      kubectl -n "$NAMESPACE" patch volumes.longhorn.io "$vol" \
        --type merge -p "{\"spec\":{\"engineImage\":\"$target_image\"}}" \
        || warn "  Failed to patch $vol — may need manual intervention"
    fi
  done

  # Wait for engines to finish upgrading
  local start=$(date +%s)
  while true; do
    local upgrading
    upgrading=$(kubectl -n "$NAMESPACE" get volumes.longhorn.io -o json \
      | jq "[.items[] | select(.status.currentImage != \"$target_image\" and .status.state == \"attached\")] | length")
    if [[ "$upgrading" -eq 0 ]]; then
      info "All engines upgraded to v${target_version}."
      return 0
    fi
    local elapsed=$(( $(date +%s) - start ))
    if [[ "$elapsed" -ge "$ENGINE_UPGRADE_TIMEOUT" ]]; then
      error "Timeout waiting for engine upgrades. $upgrading volumes still upgrading."
      return 1
    fi
    sleep 10
  done
}

snapshot_state() {
  local label="$1"
  local dir="/tmp/longhorn-state-${label}"
  mkdir -p "$dir"
  info "Capturing cluster state snapshot: $label → $dir"

  kubectl -n "$NAMESPACE" get all -o yaml > "$dir/all-resources.yaml" 2>/dev/null || true
  kubectl -n "$NAMESPACE" get volumes.longhorn.io -o yaml > "$dir/volumes.yaml" 2>/dev/null || true
  kubectl -n "$NAMESPACE" get engineimages.longhorn.io -o yaml > "$dir/engineimages.yaml" 2>/dev/null || true
  kubectl -n "$NAMESPACE" get nodes.longhorn.io -o yaml > "$dir/nodes.yaml" 2>/dev/null || true
  kubectl -n "$NAMESPACE" get settings.longhorn.io -o yaml > "$dir/settings.yaml" 2>/dev/null || true
  kubectl get sc -o yaml > "$dir/storageclasses.yaml" 2>/dev/null || true

  info "State snapshot saved to $dir"
}

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
preflight() {
  info "========================================="
  info "Pre-flight checks"
  info "========================================="

  # Check kubectl
  command -v kubectl >/dev/null || fatal "kubectl not found"
  command -v jq >/dev/null || fatal "jq not found"

  # Check cluster connectivity
  kubectl cluster-info >/dev/null 2>&1 || fatal "Cannot connect to cluster"

  # Check current version
  local cur
  cur=$(current_version)
  info "Current Longhorn version: $cur"
  if [[ "$cur" != 1.5.* ]]; then
    warn "Expected 1.5.x, detected $cur. Adjust UPGRADE_PATH if needed."
  fi

  # Check Kubernetes version
  local k8s_version
  k8s_version=$(kubectl version -o json 2>/dev/null | jq -r '.serverVersion.minor' | tr -d '+')
  info "Kubernetes minor version: $k8s_version"
  if [[ "$k8s_version" -lt 25 ]]; then
    warn "Kubernetes < 1.25 detected. Longhorn 1.8+ requires >= 1.25."
    warn "You MUST upgrade Kubernetes before reaching 1.8.x step."
  fi

  # Check kernel version
  local sample_node
  sample_node=$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')
  local kernel
  kernel=$(kubectl get node "$sample_node" -o jsonpath='{.status.nodeInfo.kernelVersion}')
  info "Sample node kernel: $kernel"

  # Check volumes health
  local unhealthy
  unhealthy=$(kubectl -n "$NAMESPACE" get volumes.longhorn.io -o json 2>/dev/null \
    | jq '[.items[] | select(.status.state == "attached" and .status.robustness != "healthy")] | length' || echo "0")
  if [[ "$unhealthy" -gt 0 ]]; then
    fatal "$unhealthy unhealthy volumes detected. Resolve before upgrading."
  fi
  info "All attached volumes healthy."

  # Check backups exist (advisory)
  if [[ "$SKIP_BACKUP_CHECK" != "true" ]]; then
    local backup_count
    backup_count=$(kubectl -n "$NAMESPACE" get backups.longhorn.io --no-headers 2>/dev/null | wc -l || echo "0")
    if [[ "$backup_count" -eq 0 ]]; then
      warn "No Longhorn backups found. STRONGLY recommend backing up all volumes first."
      warn "Set SKIP_BACKUP_CHECK=true to proceed anyway."
      read -rp "Continue without backups? (yes/no): " answer
      [[ "$answer" == "yes" ]] || fatal "Aborted. Create backups first."
    else
      info "Found $backup_count backups."
    fi
  fi

  # Check CSI snapshot CRD version (needed for 1.6+)
  local csi_snap_version
  csi_snap_version=$(kubectl get crd volumesnapshots.snapshot.storage.k8s.io -o json 2>/dev/null \
    | jq -r '.spec.versions[] | select(.served==true) | .name' | head -1 || echo "none")
  info "CSI snapshot CRD version: $csi_snap_version"
  if [[ "$csi_snap_version" == "v1beta1" ]]; then
    warn "CSI snapshot CRDs still on v1beta1 — must upgrade to v1 before Longhorn 1.6."
  fi

  # Snapshot current state
  snapshot_state "pre-upgrade-$(current_version)"

  info "Pre-flight checks complete."
  echo ""
}

# ---------------------------------------------------------------------------
# CRD v1beta1 → v1beta2 migration (required before 1.10)
# ---------------------------------------------------------------------------
migrate_crd_stored_versions() {
  info "Migrating CRD storedVersions from v1beta1 → v1beta2..."

  local crds
  crds=$(kubectl get crd -o json \
    | jq -r '.items[] | select(.spec.group=="longhorn.io") | .metadata.name')

  for crd in $crds; do
    local has_v1beta1
    has_v1beta1=$(kubectl get crd "$crd" -o json \
      | jq '[.status.storedVersions[] | select(. == "v1beta1")] | length')
    if [[ "$has_v1beta1" -gt 0 ]]; then
      info "  Migrating $crd storedVersions..."
      if [[ "$DRY_RUN" == "false" ]]; then
        # Force-migrate: read all CRs and re-write them to trigger v1beta2 storage
        local items
        items=$(kubectl -n "$NAMESPACE" get "$crd" -o json 2>/dev/null \
          | jq -r '.items[].metadata.name' || true)
        for item in $items; do
          kubectl -n "$NAMESPACE" get "$crd" "$item" -o json \
            | kubectl replace -f - >/dev/null 2>&1 || true
        done
        # Patch CRD to remove v1beta1 from storedVersions
        kubectl patch crd "$crd" --type=json \
          -p='[{"op":"replace","path":"/status/storedVersions","value":["v1beta2"]}]' \
          --subresource=status 2>/dev/null \
          || warn "  Could not patch storedVersions for $crd — may need manual fix"
      fi
    fi
  done
  info "CRD migration complete."
}

# ---------------------------------------------------------------------------
# Single version upgrade step
# ---------------------------------------------------------------------------
upgrade_to_version() {
  local target="$1"
  local current
  current=$(current_version)

  info "========================================="
  info "UPGRADE: v${current} → v${target}"
  info "========================================="

  # Print breaking changes
  if [[ -n "${VERSION_NOTES[$target]:-}" ]]; then
    info "Version notes for v${target}:"
    echo "${VERSION_NOTES[$target]}" | tee -a "$LOG_FILE"
  fi

  # Pre-1.10 CRD migration
  if [[ "$target" == 1.10.* ]]; then
    migrate_crd_stored_versions
  fi

  # Download and apply manifest
  local manifest_url="https://raw.githubusercontent.com/longhorn/longhorn/v${target}/deploy/longhorn.yaml"
  local manifest_file="/tmp/longhorn-v${target}.yaml"

  info "Downloading manifest from: $manifest_url"
  if ! curl -sSfL "$manifest_url" -o "$manifest_file"; then
    fatal "Failed to download manifest for v${target}"
  fi
  info "Manifest downloaded: $(wc -c < "$manifest_file") bytes"

  if [[ "$DRY_RUN" == "true" ]]; then
    info "[DRY RUN] Would apply: kubectl apply -f $manifest_file"
    return 0
  fi

  # Apply
  info "Applying manifest..."
  if ! kubectl apply -f "$manifest_file" 2>&1 | tee -a "$LOG_FILE"; then
    error "kubectl apply failed for v${target}"
    error "Attempting rollback..."
    rollback_manifest "$current"
    fatal "Upgrade to v${target} failed. Rolled back to v${current}."
  fi

  # Wait for manager pods
  info "Waiting ${SETTLE_DELAY}s for rollout to begin..."
  sleep "$SETTLE_DELAY"

  if ! wait_for_pods_ready "$MANAGER_READY_TIMEOUT"; then
    error "Pods not ready after upgrade to v${target}"
    error "Attempting rollback..."
    rollback_manifest "$current"
    fatal "Upgrade to v${target} failed (pods). Rolled back to v${current}."
  fi

  # Verify version changed
  local new_ver
  new_ver=$(current_version)
  info "Detected version after upgrade: $new_ver"
  if [[ "$new_ver" != "$target" ]]; then
    warn "Version mismatch: expected $target, got $new_ver"
  fi

  # Upgrade engines
  if [[ "$AUTO_ENGINE_UPGRADE" == "true" ]]; then
    if ! upgrade_engines "$target"; then
      warn "Engine upgrade had issues — check manually."
    fi
  else
    info "AUTO_ENGINE_UPGRADE=false — skipping automatic engine upgrade."
    info "Upgrade engines manually via UI or API before proceeding."
    read -rp "Press Enter after engines are upgraded..."
  fi

  # Wait for volumes
  if ! wait_for_volumes_healthy "$VOLUME_HEALTHY_TIMEOUT"; then
    warn "Some volumes not healthy after upgrade to v${target}."
    warn "Review volume status before proceeding."
    read -rp "Continue to next version? (yes/no): " answer
    [[ "$answer" == "yes" ]] || fatal "Aborted after v${target} upgrade."
  fi

  # Snapshot post-upgrade state
  snapshot_state "post-upgrade-v${target}"

  info "✓ Upgrade to v${target} complete."
  echo ""
}

rollback_manifest() {
  local version="$1"
  warn "Rolling back to v${version}..."
  local manifest_file="/tmp/longhorn-v${version}.yaml"
  if [[ -f "$manifest_file" ]]; then
    kubectl apply -f "$manifest_file" 2>&1 | tee -a "$LOG_FILE" || true
  else
    local url="https://raw.githubusercontent.com/longhorn/longhorn/v${version}/deploy/longhorn.yaml"
    curl -sSfL "$url" | kubectl apply -f - 2>&1 | tee -a "$LOG_FILE" || true
  fi
  sleep "$SETTLE_DELAY"
  wait_for_pods_ready "$MANAGER_READY_TIMEOUT" || true
}

# ---------------------------------------------------------------------------
# Validation suite — run after final upgrade
# ---------------------------------------------------------------------------
final_validation() {
  info "========================================="
  info "Final validation"
  info "========================================="

  local ver
  ver=$(current_version)
  info "Current version: $ver"

  # Pods
  info "Pod status:"
  kubectl -n "$NAMESPACE" get pods --no-headers | tee -a "$LOG_FILE"

  # Volumes
  info "Volume status:"
  kubectl -n "$NAMESPACE" get volumes.longhorn.io \
    -o custom-columns='NAME:.metadata.name,STATE:.status.state,ROBUSTNESS:.status.robustness,ENGINE_IMAGE:.status.currentImage' \
    | tee -a "$LOG_FILE"

  # Nodes
  info "Node status:"
  kubectl -n "$NAMESPACE" get nodes.longhorn.io \
    -o custom-columns='NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status' \
    | tee -a "$LOG_FILE"

  # Engine images
  info "Engine images:"
  kubectl -n "$NAMESPACE" get engineimages.longhorn.io \
    -o custom-columns='NAME:.metadata.name,STATE:.status.state,IMAGE:.spec.image' \
    | tee -a "$LOG_FILE"

  # CRD versions — confirm no v1beta1
  info "CRD storedVersions check:"
  kubectl get crd -o json \
    | jq -r '.items[] | select(.spec.group=="longhorn.io") | "\(.metadata.name): \(.status.storedVersions)"' \
    | tee -a "$LOG_FILE"

  local v1beta1_count
  v1beta1_count=$(kubectl get crd -o json \
    | jq '[.items[] | select(.spec.group=="longhorn.io") | .status.storedVersions[] | select(. == "v1beta1")] | length')
  if [[ "$v1beta1_count" -gt 0 ]]; then
    warn "v1beta1 still present in $v1beta1_count CRD storedVersions entries!"
  else
    info "✓ No v1beta1 storedVersions remain."
  fi

  # PVC/PV sanity
  info "PVC status:"
  kubectl get pvc --all-namespaces \
    --field-selector='metadata.annotations.volume\.beta\.kubernetes\.io/storage-provisioner=driver.longhorn.io' \
    2>/dev/null | head -20 | tee -a "$LOG_FILE" || \
  kubectl get pvc --all-namespaces 2>/dev/null | grep longhorn | head -20 | tee -a "$LOG_FILE" || true

  info "========================================="
  info "Upgrade complete. Log: $LOG_FILE"
  info "========================================="
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
  info "========================================="
  info "Longhorn Upgrade: 1.5.3 → 1.10.2"
  info "========================================="
  info "Upgrade path: 1.5.3 → ${UPGRADE_PATH[*]}"
  info "Log file: $LOG_FILE"
  info "Dry run: $DRY_RUN"
  echo ""

  preflight

  if [[ "$DRY_RUN" == "true" ]]; then
    info "=== DRY RUN MODE — no changes will be made ==="
  fi

  for version in "${UPGRADE_PATH[@]}"; do
    upgrade_to_version "$version"
  done

  final_validation
}

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
case "${1:-run}" in
  run)
    main
    ;;
  dry-run)
    DRY_RUN=true main
    ;;
  preflight)
    preflight
    ;;
  validate)
    final_validation
    ;;
  migrate-crds)
    migrate_crd_stored_versions
    ;;
  *)
    echo "Usage: $0 {run|dry-run|preflight|validate|migrate-crds}"
    echo ""
    echo "  run          - Execute full upgrade path (interactive)"
    echo "  dry-run      - Show what would happen without making changes"
    echo "  preflight    - Run pre-flight checks only"
    echo "  validate     - Run post-upgrade validation only"
    echo "  migrate-crds - Run CRD v1beta1→v1beta2 migration only"
    echo ""
    echo "Environment variables:"
    echo "  DRY_RUN=true              Skip actual kubectl apply"
    echo "  SKIP_BACKUP_CHECK=true    Don't warn about missing backups"
    echo "  AUTO_ENGINE_UPGRADE=false  Don't auto-upgrade engines (do manually)"
    exit 1
    ;;
esac
