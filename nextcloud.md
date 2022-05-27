nextcloud
---

This is an old macbook pro. It *used* to run Nextcloud, but now only the hostname remains to confuse us. 

### Notes

* This system doesn't have a working ATA controller on the mobo, so the hard drive is USB.
* NFS storage from `warehouse` is mounted in /media/bigdrive
* Requires hand installation of macfanctld through apt-get. I also lowered the default temperature thresholds to run a bit cooler.
* I wrote a script to adjust the screen backlight, at /usr/local/bin/brightness . tldr: `brightness up` and `brightness down`

