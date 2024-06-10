# Home Network Documentaion

This repo documents my home network. It's intended mostly for me, but potentially also as a disaster recovery plan, just in case.

These are the servers on this network:
* dns: pair of raspberry pi 3b+, runs pi.hole DNS/DHCP in a HA configuration. Setup in Ansible](https://github.com/ohthehugemanatee/ansible-pihole).
* shoebox: data storage only. Serves `/mnt/storage` over NFS and CIFS.
* homeassistant: Raspberry Pi 4 running home assistant in a default configuration.

All other hosts form a mixed arm64/amd64 k3s cluster. The Raspberry Pi 4 hosts are the master nodes in a HA configuration.

k3s nodes:
| name | arch | device type |
| --- | --- | --- |
| cluster1 | arm64 | rpi4 |
| cluster3 | arm64 | rpi4 |
| cluster4 | arm64 | rpi4 |
| airbernetes | amd64 | macbook air 2011 13" |
| celery | amd64 | celeron mini-pc |
| fuji | amd64 | i5 4th-gen mini-pc |
| nuc1 | amd64 | i3-1115G4 mini-pc |
| nuc2 | amd64 | i3-10110U CPU mini-pc |

All services run on kubernetes, with the yaml files listed in the `cluster/` subdirectory.

Nodes with a useful GPU - ie a recent enough generation for video transcoding - are labeled with transcodingGpu=1.

Access to all the machines is keyed on my ssh keypair.


