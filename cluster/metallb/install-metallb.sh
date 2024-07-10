#!/bin/bash

# Install metallb.

# Get current version from metallb docs: https://metallb.io/installation/
kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.14.5/config/manifests/metallb-native.yaml

kubectl apply -f l2-config.yaml

kubectl patch -n kube-system traefik -p '{"spec":{"LoadBalancerIP":"10.10.11.2"}}'
