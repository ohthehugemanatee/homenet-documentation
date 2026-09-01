# ADR-0006: Memory limits are sized from the image; CPU is requests-only

- **Status:** accepted
- **Date:** 2026-09-01

## Context

Alloy ran with a 256Mi memory limit, below the 273 MB it needed. The kernel evicted 
and refaulted from the USB disk at ~ 84,000 pages per second, saturating I/O and CPU
on the control plane nodes. Clearly I need to get intentional about limits/requests.

Right now only 6 workloads set a CPU limit and 1 namespace sets a LimitRange, with 
no documented policy.

## Decision

Every container declares a CPU request and a memory request. Memory request equals
memory limit.

No container sets a CPU limit. A workload that has demonstrated a runaway may carry
one with a reason documented in code.

Memory is sized as 1.5x observed steady-state usage, or the largest file-backed 
segment the image maps, whichever is larger. 

## Consequences

Pods stay Burstable, since Guaranteed QoS also requires a CPU limit. Eviction
protection comes from kubelet ranking usage against request. 

Since inaccurate requests will be contention bugs, sizing needs to be based on
measurement. 

Not covered by this ADR: 

- Namespace LimitRanges as a backstop
- System resource reservation for x86 worker nodes

