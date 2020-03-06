# Home Network Documentaion

This repo documents my home network. It's intended mostly for me, but potentially also as a disaster recovery plan, just in case.

There are four servers on this network:
* warehouse: data storage, downloads, and backup
* cluster1: rpi, master for a small k3s cluster
* cluster2: DHCP, DNS, k3s agent.
* nextcloud: aka "frontdoor"
  * NGINX proxy in front of everything else
  * organizr for access to it all. Access control to all internal services is done by testing for the presence of a valid organizr cookie.
  * Nextcloud itself.
  * Netdata registry and central monitoring dashboard.

Check out the individual docs for details.

## TODO
* Keep plugging at signal photo mailer. It's not sending yet!
* Add https://github.com/bank2ynab/bank2ynab
* Fix DNS behavior on internet disconnection
* Fix boot order of Nextcloud server
