# OpenBao — central keystore for homenet

OpenBao (MPL-2.0, Linux Foundation fork of HashiCorp Vault) runs on shoebox as
a Docker Compose service. It provides an HTTP API that Ansible queries at playbook
runtime, replacing the ansible-vault flat-file password pattern.

See Issue #9 for the full alternatives evaluation (SOPS, Sealed Secrets, Infisical,
HashiCorp Vault) and why OpenBao was selected.

---

## Initial deployment

```sh
ansible-playbook -i cluster/ansible/inventory.yaml cluster/ansible/deploy-openbao.yaml
```

## Init and unseal

```sh
# Init — run once; generates unseal keys and root token
docker exec openbao bao operator init -key-shares=3 -key-threshold=2

# Store the 3 unseal keys and root token OFFLINE (password manager / paper).
# You need any 2 of the 3 unseal keys to unseal after a reboot.

# Unseal (run twice with two different keys)
docker exec openbao bao operator unseal <key-1>
docker exec openbao bao operator unseal <key-2>

docker exec openbao bao status  # verify
```

## KV engine and initial secrets

```sh
export VAULT_ADDR=http://shoebox.vert:8200
export VAULT_TOKEN=<root-token>  # create a scoped token before regular use

bao secrets enable -path=secret kv

# Populate secrets (values from old group_vars/vault.yaml)
bao kv put secret/k3s/cluster           token=<k3s-join-token>
bao kv put secret/cluster/pushover      app_token=<VALUE> user_key=<VALUE>
bao kv put secret/cluster/semaphore     admin_password=<VALUE> access_key_encryption=<VALUE>
bao kv put secret/cluster/ansible       vault_password=migrated-to-openbao

# Create a scoped Ansible token (uses policies/ansible-read.hcl)
bao policy write ansible-read cluster/openbao/policies/ansible-read.hcl
bao token create -policy=ansible-read -display-name=semaphore
# → store the resulting token as VAULT_TOKEN in Semaphore project environment

# Revoke the root token — only use unseal-key-derived root for break-glass operations
bao token revoke <root-token>
```

## Unseal after reboot

OpenBao starts sealed after every reboot:

```sh
docker exec openbao bao operator unseal <key-1>
docker exec openbao bao operator unseal <key-2>
```

---

## Day-2 operations

### Rotate the Ansible token

```sh
bao token create -policy=ansible-read -display-name=semaphore
# update VAULT_TOKEN in Semaphore project settings
bao token revoke <old-token>
```

### Rotate unseal keys

```sh
bao operator rekey -init -key-shares=3 -key-threshold=2
# supply current unseal keys one at a time when prompted
```

### k3s encryption key rotation

See `cluster/ansible/enable-k3s-encryption.yaml` header comment for the
three-step rotation procedure (add new key → re-encrypt all Secrets → remove old key).

---

## Security notes

- **Port binding**: OpenBao listens on `0.0.0.0:8200` because Semaphore runs as a Docker
  container and needs to reach OpenBao via the host's LAN IP (`shoebox.vert:8200`).
  Binding to `127.0.0.1` would break Semaphore connectivity. Port 8201 (Raft peer) is
  NOT published — single-node deployment only.
- **TLS**: Disabled; tokens transit the private LAN in cleartext. The LAN is private and
  Semaphore's network is local. Remote operator access should use SSH tunnel
  (`ssh -L 8200:localhost:8200 shoebox`).
- Future hardening: co-locate Semaphore and OpenBao on the same Docker network so
  `127.0.0.1` binding becomes viable; enable TLS with self-signed cert.
