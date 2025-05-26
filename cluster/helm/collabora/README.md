# Collabora office

There's a basic helm chart, but the real fun begins when you want to ensure that users editing the same file end up on the same backend.This requires:

- A special traefik plugin, for hashing arbitrary request params and using them to set a cookie on the internal request. Defined in `cluster/traefik.yaml`. 
  - I also put this one on the k3s master in `/var/lib/rancher/k3s/server/manifests`, whence it should be applied on startup... just in case. 
- A special kind of traefik config for ingress, called ingressRoute. It's probably maybe could be possible using annotations on Kubernetes Ingresses, but documentation is spotty and implies that they're trying to get rid of annotation-driven config for special features. 
- Redis as a KV store between collabora instances
- A manually generated certificate request, because letsencrypt cert-manager doesn't watch IngressRoutes to automatically generate certificate requests

The ingressRoute sets a middleware processor which uses that traefik plugin. The traefik plugin requires redis as a KV store. The ingressRoute is then configured to use the cookie set by that plugin as a session stickiness key.

