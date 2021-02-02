This machine *used to* be the central server on my network. Services are gradually being migrated to the kubernetes cluster. Still remaining:

* MariaDB
* NetData central host
* Wireguard endpoint

Setup
---
* This system doesn't have a working ATA controller on the mobo, so the hard drive is USB.
* NFS storage from `warehouse` is mounted in /media/bigdrive
* Mariadb runs in docker-compose at `~/.docker/compose`, thanks to https://github.com/GhostWriters/DockSTARTer
* Requires hand installation of macfanctld through apt-get. I also lowered the default temperature thresholds to run a bit cooler.
* I wrote a script to adjust the screen backlight, at /usr/local/bin/brightness . tldr: `brightness up` and `brightness down`
* Everything configured through dockstarter lives in `~/.docker` . So a nightly crontab backs that directory up to `/mnt/storage/docker/nextcloud/` shortly before the offsite backup starts.
* The contents of the big storage drive (`/media/bigdrive`) are backed up daily using a duplicacy instance running in the cluster.


