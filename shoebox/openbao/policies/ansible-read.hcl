# Least-privilege policy for the Ansible/Semaphore service token.
# Create the policy and a token:
#   bao policy write ansible-read shoebox/openbao/policies/ansible-read.hcl
#   bao token create -policy=ansible-read -display-name=semaphore
#
# Store the resulting token in Semaphore's project environment as VAULT_TOKEN.
# Revoke the old token if rotating: bao token revoke <old-token>

# k3s join token and encryption key
path "secret/k3s/*" {
  capabilities = ["read"]
}

# Pushover alert credentials (used by upgrade rescue roles)
path "secret/cluster/pushover" {
  capabilities = ["read"]
}

# Semaphore admin credentials (used by shoebox-ansible-setup.yaml)
path "secret/cluster/semaphore" {
  capabilities = ["read"]
}

# Ansible vault password placeholder (written to /etc/ansible/vault-password)
path "secret/cluster/ansible" {
  capabilities = ["read"]
}
