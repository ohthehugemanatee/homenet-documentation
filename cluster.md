# Cluster

This is a mixed-CPU k3s cluster with agents on all available servers apart from *warehouse*. It runs every service I can think of, and uses node affinity to find compatible CPUs.

Presently running:

* Deluge + OpenVPN - connects to privateInternetAccess and torrents. 
* NzbGet - NewsBin downloader. 
* Sonarr - searches iptorrents and downloads episodes of TV shows. Can "watch" series automatically to download the latest episodes. 
* Radarr - like Sonarr, but for movies. 
* Nextcloud - my files and collaboration in the cloud.
* Signal photo mailer - my own script that listens to my family Signal group, and sends photos to my frame automatically
* cloudflare-ddns - a cloudflare DNS updater to keep my DNS current
* duplicacy - backups to Azure Blob storage

None of this is accessible outside the homenet, except for Nextcloud which gets a Letsencrypt cert.

Configuration lives in my NFS storage under `/mnt/storage/.docker/config`. 

## TODO

* Migrate plex
* Migrate mariadb
* Consider migrating Wireguard
* Consider migrating netdata monitoring
* Setup Organizr or similar again
* Document necessary secrets

