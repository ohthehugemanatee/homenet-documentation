# Home Network Documentaion

This repo documents my home network. It's intended mostly for me, but potentially also as a disaster recovery plan, just in case.

There are three servers on this network:
* warehouse: data storage, downloads, and backup
* raspberrypi: DHCP, DNS
* nextcloud: aka "frontdoor"
  * NGINX proxy in front of everything else
  * organizr for access to it all. Access control to all internal services is done by testing for the presence of a valid organizr cookie.
  * Nextcloud itself.
  * Netdata registry and central monitoring dashboard.

Check out the individual docs for details.

## TODO
* Try running all services in a mixed CPU k8s cluster instead
* Add https://github.com/ohthehugemanatee/signal-photo-mail
* Add https://github.com/bank2ynab/bank2ynab
* Fix DNS behavior on internet disconnection
