# Home Network Documentaion

This repo documents my home network. It's intended mostly for me, but potentially also as a disaster recovery plan, just in case.

These are the servers on this network:
* warehouse: data storage, downloads, and backup
* cluster1: rpi, master for a small k3s cluster
* cluster2: rpi, DHCP, DNS, k3s agent.
* nextcloud:
  * Netdata registry and central monitoring dashboard.
  * MariaDB
  * Wireguard endpoint

Check out the individual docs for details.

