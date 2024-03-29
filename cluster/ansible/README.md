# Ansible playbook for my k3s

This playbook creates masters or agent nodes for my home k3s cluster. It uses ansible variables for simple differences between types of nodes.

## Variables

| **Name** | **Function** | **Example value** |
| `new_hostname` | Hostname to set for the device | `cluster2` |
| `ansible_user` | SSH Username for connecting to the node | `ubuntu` |
| `k3s_token` | K3s token to pass to the installer | |
| `usb_disk` | If there is a USB disk to use as storage (mostly on raspberry pis), path to the block device. | `/dev/sda1` |
| `cluster_role` | Role of this node in the cluster. Can be: `agent`, `multi-master`, or `first-master` | `agent` |


Usage:

```
# Set up a new ubuntu node as an agent called cluster2, with a USB disk attached.
ansible-playbook -i cluster2,ubuntu -e usb_disk='/dev/sda1' --ask-vault-pass --ask-become-pass k3s-node.yaml
# The same, but manually specify available variables.
ansible-playbook -i cluster2,ubuntu -e new_hostname=cluster2 -e ansible_user=ubuntu -e k3s_token="${K3S_TOKEN}" -e usb_disk='/dev/sda1' -e cluster_role="agent" --ask-become-pass --ask-vault-pass k3s-node.yaml 
```

Notes from the example:

- we apply to both the OOTB hostname ("ubuntu") and the final hostname ("cluster2"). If an "ubuntu" host exists, the playbook will automatically change hostname and reboot before applying the agent config to "cluster2".
- Since it needs sudo access, `--ask-become-pass` is important 
