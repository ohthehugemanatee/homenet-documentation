# Home Network Documentaion

This repo documents my home network. It's intended mostly for me, but potentially also as a disaster recovery plan, just in case.

These are the servers on this network:
* dns: rpi3, runs pi.hole DNS/DHCP.
* warehouse: data storage only. Serves `/mnt/storage` over NFS and CIFS.

All other hosts form a mixed arm64/amd64 k3s cluster. The Raspberry Pi 4 host `cluster1` is the master.

k3s nodes:
| name | arch | device type |
| --- | --- | --- |
| cluster2 | arm64 | rpi4 |
| cluster3 | arm64 | rpi4 |
| cluster4 | arm64 | rpi4 |
| nextcloud | amd64 | macbook pro 2014 15" |
| airbernetes | amd64 | macbook air 2011 13" |
| celery | amd64 | celeron mini-pc |
| fiji | amd64 | i5 4th-gen mini-pc |

All services run on kubernetes, with the yaml files listed in the `cluster/` subdirectory.

Access to all the machines is keyed on my ssh keypair.
