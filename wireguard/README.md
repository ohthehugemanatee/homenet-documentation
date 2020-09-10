# Wireguard

My wireguard config runs on docker-compose. It's possible to run it through k8s, but it's hacky and needs access to a specfic node kernel anyway.

This docker-compose file sets a specific static IP for the wireguard host, which is allowed to access the web services inside the network.
