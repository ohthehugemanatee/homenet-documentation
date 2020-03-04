# Warehouse

This system is all about data storage. It's focused around a RAID5 cluster of old 1TB disks I had kicking around, `/dev/md0`. This is mounted at `/mnt/storage`. It is shared over NFS and SAMBA. It runs regular backups to gpg-encrypted Azure Blob storage using Duplicity.

