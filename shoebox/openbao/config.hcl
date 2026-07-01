storage "raft" {
  path    = "/openbao/data"
  node_id = "shoebox"
}

# TLS is disabled; OpenBao listens on all interfaces on the LAN.
# Mitigations: token-based auth gates all secret reads; the LAN is private;
# operator CLI access requires being on-LAN or via SSH tunnel.
# Future: enable TLS with a self-signed cert + VAULT_CACERT if threat model warrants.
listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
}

api_addr     = "http://shoebox.vert:8200"
cluster_addr = "http://shoebox.vert:8201"
ui           = true
