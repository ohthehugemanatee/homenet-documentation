# Warehouse

This system is all about data storage. It's focused around a RAID5 cluster of old 1TB disks I had kicking around, `/dev/md0`. This is mounted at `/mnt/storage`. It is shared over NFS and SAMBA.

On init it enables a [BPF filter](https://github.com/ohthehugemanatee/filter-powerline) to block out extraneous Powerline ("Homeplug AV") calls from my Fritzbox router.

