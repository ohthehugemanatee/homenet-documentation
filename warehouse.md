# Warehouse

This system is all about data storage. It's focused around a RAID5 cluster of old 1TB disks I had kicking around, `/dev/md0`. This is mounted at `/mnt/storage`. It is shared over NFS and SAMBA. It runs regular backups to gpg-encrypted Azure Blob storage using Duplicity.

It uses [dockstarter](https://github.com/GhostWriters/DockSTARTer) to manage an array of services for downloading TV shows and movies automagically. the `ds` command generates a `.env` and docker-compose file at ~/.docker/compose . Generally should be interacted with using `ds`, see the repo for documentation. These containers run:

* Deluge + OpenVPN - connects to privateInternetAccess and torrents. Web UI at [http://warehouse.vert:8112/](http://warehouse.vert:8112/)
* NzbGet - NewsBin downloader. Web UI at [http://warehouse.vert:6789](http://warehouse.vert:6789).
* Sonarr - searches iptorrents and downloads episodes of TV shows. Can "watch" series automatically to download the latest episodes. Web UI at [http://warehouse.vert:8989/](http://warehouse.vert:8989/)
* Radarr - like Sonarr, but for movies. Web UI: [http://warehouse.vert:7878](http://warehouse.vert:7878)
* Jackett - Translation layer beteween Sonarr and IPTorrents. Web UI: [http://warehouse.vert:9117/](http://warehouse.vert:9117/UI/Dashboard)

None of this is accessible outside the homenet, except through the `frontdoor` instance at internal.germany.vertesi.com . See that server's reade for details.

@todo:
* Configure bazarr [http://warehouse.vert:6767/](http://warehouse.vert:6767/). It's a subtitle grabber.


