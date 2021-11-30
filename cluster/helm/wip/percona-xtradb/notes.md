# Percona xtradb cluster

The Operator creates/updates the statefulset with an invalid resources configuration. It sets "requests" but not "limits". Also there's no way to easily specify NodeSelctors, and at least some components don't run on ARM. 
