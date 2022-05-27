# Raspberrypi

This device focuses on network services. Its primary focus is DNS and DHCP. 

DNS/DHCP is two layered.
* port 53 and DHCP responses are handled by [pihole](https://pi-hole.net/). It has a forked version of dnsmasq, called pihole-FTL, which runs both services. Its configuration is 99% automatic. You can view metrics at [http://raspberrypi/admin](http://raspberrypi/admin/). It is set up to create host entries under the `.vert` local domain for every dhcp lease. Normal leases are in the `192.168.1.100-200` range. Static IPs are set for the other servers in the first 100 addresses. These are configured through the web interface.
* Pihole forwards non-local DNS requests to its "upstream" server, 127.0.0.1:8053, the DNS server run by cloudflared. This server forwards DNS requests over DNS-over-HTTPS to the cloudflare/mozilla 1.1.1.1 service. It falls back to 8.8.8.8.

I set this up with the help of [this blog post](https://scotthelme.co.uk/securing-dns-across-all-of-my-devices-with-pihole-dns-over-https-1-1-1-1/).

Adding custom hostnames is as easy as adding them to `/etc/hosts`.
