# ADR-0009: Nextcloud application files use Longhorn

- **Status:** accepted
- **Date:** 2026-10-22

## Context

Nextcloud's PHP tree has many small files, and loading it from NFS was slow. The
split `/www` Longhorn volume and nested NFS config mount also left startup rsync
following a non-root-owned symlink, which rsync 3.5.0 rejected.

## Decision

Mount a dedicated Longhorn `nextcloud-config` claim at `/config`. Keep `/data`,
`/media`, and `/custom-cont-init.d` on NFS.

## Consequences

Nextcloud app files, configuration, and themes use Longhorn; user data and media
remain on NFS. The claim carries the `default` recurring-job group for scheduled
snapshots and backups.
