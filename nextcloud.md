This machine is called `frontdoor`, because it is the only externally accessible device on the network.

It hosts an NGINX reverse proxy for other services within the network, with Certbot for SSL certificates. Proxied services are:

| Service   | External URI                         | Internal URI            | Access        | Notes                                                                       |
|-----------|--------------------------------------|-------------------------|---------------|-----------------------------------------------------------------------------|
| Nextcloud | https://germany.vertesi.com          | https://localhost:444/  | It's own auth | Configured with DS                                                          |
| MariaDB   |                                      | localhost:3306          | It's own auth | Configured with DS, used for Nextcloud                                      |
| Organizr  | https://internal.germany.vertesi.com | http://localhost:8006   | It's own auth | Front for all other services. Configured with DS.                           |
| Deluge    | https://deluge.germany.vertesi.com   | http://warehouse:8112   | Organizr      | Torrent client, only connection is through privateInternetAccess.           |
| NetData   | https://monitor.germany.vertesi.com  | http://localhost:199999 | Organizr      | Collects stats for all other machines on the network. Runs on this machine. |
| NzbGet    | https://nzbget.germany.vertesi.com   | http://warehouse:6789   | Organizr      |  Newsbin downloader.                                                        |
| Plex      | https://plex.germany.vertesi.com     | http://localhost:32400  | Organizr      | Configured with DS.                                                         |
| Radarr    | https://radarr.germany.vertesi.com   | http://warehouse:7878   | Organizr      |  Movie Downloader                                                           |
| Sonarr    | https://sonarr.germany.vertesi.com   | http://warehouse:8989   | Organizr      | TV show Downloader                                                          |
| Ouroboros |                                      |                         |               | Automatically updates other containers running on this machine.             |



Setup
---
* This system doesn't have a working ATA controller on the mobo, so the hard drive is USB.
* NFS storage from `warehouse` is mounted in /media/bigdrive
* Plex, nextcloud (and its mariadb), ouroburos, and organizr run in containers, thanks to https://github.com/GhostWriters/DockSTARTer
* Requires hand installation of macfanctld through apt-get. I also lowered the default temperature thresholds to run a bit cooler.
* I wrote a script to adjust the screen backlight, at /usr/local/bin/brightness . tldr: `brightness up` and `brightness down`
* Everything configured through dockstarter lives in `~/.docker` . So a nightly crontab backs that directory up to `/mnt/storage/docker/nextcloud/` shortly before the offsite backup starts.
* The contents of the big storage drive (`/media/bigdrive`) are backed up daily using borg-backup, using a script in `/usr/local/bin/borg-backup.sh`. Backups are stored encrypted on blob storage in my personal azure account. (Credentials in Bitwarden)


TODO
---
