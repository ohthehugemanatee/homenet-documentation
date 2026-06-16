# kube-vip — control-plane VIP

Leader-elected floating VIP `10.10.10.9:6443` across the three k3s masters, so the
API/registration endpoint survives any one master going down. ARP/L2 mode (matches
the MetalLB L2 setup); `svc_enable=false` leaves Service LoadBalancers to MetalLB.

Not deployed via Argo — Argo needs a reachable API server to sync, and kube-vip is
what *provides* it. The `kube_vip` Ansible role (`cluster/ansible/roles/kube_vip/`)
copies `kube-vip.yaml` to `/var/lib/rancher/k3s/server/manifests/` on the masters,
where k3s auto-applies it at startup, below Argo. `kube-vip.yaml` here is the single
source of truth; edit it, not the on-host copy.

`vip_interface` is omitted so kube-vip auto-detects the default-route interface. Pin
it (e.g. `eth0`) by adding the env var if auto-detection picks the wrong NIC.

Verify: `curl -k https://10.10.10.9:6443/healthz` returns `ok`, and the VIP stays
reachable when the master currently holding it reboots.
