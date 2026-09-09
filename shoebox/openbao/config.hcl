storage "raft" {
  path    = "/openbao/data"
  node_id = "shoebox"
}

# TLS is disabled; OpenBao listens on all interfaces on the LAN.
# Mitigations: token-based auth gates all secret reads; the LAN is private;
# operator CLI access requires being on-LAN or via SSH tunnel.
# TLS with a Let's Encrypt cert for shoebox.berlin.vertesi.com is tracked in #328.
listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
}

api_addr     = "http://shoebox.berlin.vertesi.com:8200"
cluster_addr = "http://shoebox.berlin.vertesi.com:8201"
ui           = true
