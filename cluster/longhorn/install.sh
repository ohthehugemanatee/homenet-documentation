#!/bin/sh

# Install longhorn

# This was master's commit hash today, when I installed.
kubectl apply -f  https://raw.githubusercontent.com/longhorn/longhorn/159f44a0c565283ad4c02feeb4c54e920e4396f8/deploy/longhorn.yaml 

