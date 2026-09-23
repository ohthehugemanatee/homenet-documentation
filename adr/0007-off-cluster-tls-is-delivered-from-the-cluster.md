# ADR-0007: Off-cluster TLS is delivered from the cluster on a schedule

- **Status:** accepted
- **Date:** 2026-09-23

## Context

The only TLS termination point on this network is a k3s Ingress. Everything behind it
on a host outside the cluster — OpenBao, Semaphore, the OpenMediaVault UI, the Pi-hole
pair — is reached over cleartext HTTP on the LAN. cert-manager already issues publicly
trusted certificates for any `vertesi.com` name through the Cloudflare DNS-01 solver,
so the missing piece was delivery, not issuance.

The alternative is an ACME client per host with its own scoped Cloudflare token,
which drops the dependency on cluster uptime. It also puts one more thing on each host
that can stop renewing without failing anything visible, each with its own failure mode
and no shared alerting.

`cluster/ansible/` held node provisioning (ADR-0002) and then operations against
cluster workloads (ADR-0005). Neither covers moving material out of the cluster.

## Decision

cert-manager issues one `Certificate` per off-cluster host into the `offcluster-tls`
namespace, and `cluster/ansible/deliver-tls-certs.yaml` delivers each `Secret` to its
host daily from the Semaphore schedule. Consumers terminate their own TLS. No private
CA, no trust bundle, no ACME client outside the cluster.

The delivery playbook reads no ansible-vault secrets. After part 2 of #9 Ansible reads
its secrets from OpenBao, and a delivery job that needed OpenBao could not be the thing
that fixes OpenBao when an expired certificate has taken it down.

## Consequences

- `cluster/ansible/` now holds a third category of work. ADR-0002's reasoning for the
  path is unchanged, and ADR-0005's contract for reaching the API server is reused as is.
- Off-cluster TLS depends on cluster uptime and on one schedule. The guard is the
  `tls_cert_min_days` assert: the run fails while the certificate still has a month
  left, so a job that has stopped running raises an alert rather than letting a
  certificate expire.
- Cluster-issued private keys land on hosts outside the cluster. They are per-host and
  per-name, so losing shoebox costs the names in shoebox's certificate and nothing else.
- Home Assistant OS is a named exception. It has no SSH and no Python, so Ansible cannot
  reach it; it runs its own ACME add-on (#369) and is not covered by this job's alerting.
