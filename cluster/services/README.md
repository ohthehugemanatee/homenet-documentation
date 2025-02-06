# README

Most of the services here are self-explanatory. BUT nextcloud is the most critical service I run, so it has an A/B deployment process for updates.

Everything you need is contained in the nextcloud-alpha.yaml file. There are persistent volumes and claims that I just leave standing in longhorn for mariadb and nextcloud configs; they are clones of the production db and config volumes which I only use for update purposes. I generally don't bother recreating them each time, so if something goes wrong that's probably the first thing to try. Burn the clones and recreate them, then try the upgrade again.

When you're done with the upgrade just kubectl delete the entire nextcloud-alpha.yaml file until next time.
