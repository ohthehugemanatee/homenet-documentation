# MariaDB Galera

I tried using the Bitnami chart for this, but if the cluster ever shuts down uncleanly - say, because you restarted nodes or killed pods - it can never start up cleanly again. Still not really sure why.

I've deleted EVERYTHING: helm uninstall, manually make sure there are no stragglers with k get all...  but still on first boot, according to the logs it's trying to recover some previous boot. I can't imagine where that inforamtion is coming from, unless it's using some fixed naming convention to get a hostdir or something.
