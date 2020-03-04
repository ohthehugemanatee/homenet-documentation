# Cluster

This is a mixed-CPU k3s cluster with agents on all available servers apart from *warehouse*. It runs every service I can think of, and uses node affinity to find compatible CPUs.

Presently running:

* Deluge + OpenVPN - connects to privateInternetAccess and torrents. Web UI at [http://deluge.cluster.vert](http://deluge.cluster.vert/)
* NzbGet - NewsBin downloader. Web UI at [http://nzbget.cluster.vert](http://nzbget.cluster.vert)
* Sonarr - searches iptorrents and downloads episodes of TV shows. Can "watch" series automatically to download the latest episodes. Web UI at [http://sonarr.cluster.vert](http://sonarr.cluster.vert)
* Radarr - like Sonarr, but for movies. Web UI: [http://radarr.cluster.vert](http://radarr.cluster.vert)
* Jackett - Translation layer beteween Sonarr and IPTorrents. Web UI: [http://jackett.cluster.vert/](http://jackett.cluster.vert/UI/Dashboard)

None of this is accessible outside the homenet, except through the `frontdoor` instance.

Configuration lives in `/mnt/storage/.docker/config`. All storage is shared out over NFS. 
