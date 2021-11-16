#!/bin/sh

HELPTEXT="\n
# Small script to mount a loopback filesystem and use it for active storage,\n
# periodically syncing it back to a more durable storage.\n
# \n
# This is mostly useful for situations where your software doesn't support your \n
# long term storage mechanism, ie Sqlite3 WAL databases with NFS storage, or \n
# maybe where your durable storage system is very slow. You can keep your active \n
# storage on a ramdisk and periodically sync it back to durable. \n
# \n
# Usage: sync-storage --storage=[durable storage path] --active_storage=[active storage path] --image=[path for active storage image] --size=[active storage size] --period=[sync period in seconds] \n
# \n
# Default parameters:\n
# storage=/tmp/durable-storage\n
# active_storage=/mnt/active-storage\n
# image=/tmp/ramdisk\n
# size=400M\n
# period=172800\n
#\n"

STORAGE=/tmp/durable-storage
RAMDISK_MOUNTPOINT=/mnt/active-storage
RAMDISK=/tmp/ramdisk
SIZE=400M
SYNCPERIOD=172800

# Get CLI arguments.
while [ $# -gt 0 ]; do
  case "$1" in
    --storage=*)
      STORAGE="${1#*=}"
      ;;
    --active_storage=*)
      RAMDISK_MOUNTPOINT="${1#*=}"
      ;;
    --image=*)
      RAMDISK="${1#*=}"
      ;;
    --size=*)
      SIZE="${1#*=}"
      ;;
    --period=*)
      SYNCPERIOD="${1#*=}"
      ;;
    *)
      printf "***************************\n"
      printf "* Error: Invalid argument.*\n"
      printf "***************************\n"
      echo -e $HELPTEXT
      exit 1
  esac
  shift
done

printf "Creating a ${SIZE} image at ${RAMDISK}, mounting it at ${RAMDISK_MOUNTPOINT}.\n"
printf "It will sync to ${STORAGE} every ${SYNCPERIOD} seconds.\n"


# Startup. Create the image file, mount it, copy contents from durable to active storage.
startup()
{
  mkdir -p "${RAMDISK_MOUNTPOINT}"
  dd if=/dev/zero of="${RAMDISK}"/image.ext4 count=0 bs=1 seek=${SIZE}
  mkfs.ext4 "${RAMDISK}"/image.ext4;
  mount "${RAMDISK}"/image.ext4 "${RAMDISK_MOUNTPOINT}"
  cp -fvpR "${STORAGE}"/* "${RAMDISK_MOUNTPOINT}"
  printf "Image mounted and prepared.\n"
  touch "${RAMDISK_MOUNTPOINT}"/ready
}

# Synchronize from active to durable storage.
sync_to_storage()
{
  printf "Synchronizing to durable storage\n"
  sync "${RAMDISK_MOUNTPOINT}"/*
  fsfreeze --freeze "${RAMDISK_MOUNTPOINT}"
  sleep 10
  cp -fvpPR "${RAMDISK_MOUNTPOINT}"/* "${STORAGE}"
  fsfreeze --unfreeze "${RAMDISK_MOUNTPOINT}"
  printf "Sync complete\n"
}

# Clean up and exit.
cleanup()
{
  echo "EXIT called. Waiting 40 seconds for the other containers to exit..."
  sleep 40
  rm -rf "${RAMDISK_MOUNTPOINT}"/ready
  sync_to_storage
  echo "unmounting disk"
  umount "${RAMDISK_MOUNTPOINT}"
  exit 0
}

trap "cleanup" EXIT

## Program execution

startup
while true; do 
  sleep "${SYNCPERIOD}"
  sync_to_storage
done


