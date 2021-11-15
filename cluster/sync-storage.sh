#!/bin/sh

# Small script to mount a filesystem from a ramdisk and use it for active storage,
# periodically syncing it back to a more durable storage.
#
# This is mostly useful for situations where your software doesn't support your
# long term storage mechanism, ie Sqlite3 WAL databases with NFS storage.
#
# Usage: sync-storage -s [durable storage path] -r [active storage path] -s [active storage size] -p [sync period in seconds]
#


STORAGE=/tmp/sonarr-config
RAMDISK_MOUNTPOINT=/mnt/sonarr-ramdisk-mount
RAMDISK=/tmp/ramdisk
SIZE=400M
SYNCPERIOD=172800

startup()
{
  dd if=/dev/zero of="${RAMDISK}"/image.ext4 count=0 bs=1 seek=${SIZE}
  mkfs.ext4 "${RAMDISK}"/image.ext4;
  mount "${RAMDISK}"/image.ext4 "${RAMDISK_MOUNTPOINT}"
  cp -fvpR "${STORAGE}"/* "${RAMDISK_MOUNTPOINT}"
}

sync_to_storage()
{
    sync "${RAMDISK_MOUNTPOINT}"/*
    fsfreeze --freeze "${RAMDISK_MOUNTPOINT}"
    sleep 10
    cp -fvpPR "${RAMDISK_MOUNTPOINT}"/* "${STORAGE}"
    fsfreeze --unfreeze "${RAMDISK_MOUNTPOINT}"
}

cleanup()
{
  echo "EXIT called. Resyncing"
  sync_to_storage
  echo "unmounting"
  umount "${RAMDISK_MOUNTPOINT}"
  exit 0
}

trap "cleanup" EXIT

startup
while true; do 
  sleep "${SYNCPERIOD}"
  sync_to_storage
done


