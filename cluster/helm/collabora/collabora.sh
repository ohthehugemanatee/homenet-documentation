#!/bin/bash

git clone git@github.com:CollaboraOnline/online.git
kubectl create ns collabora
helm install collabora-online ./online/kubernetes/helm/collabora-online -f values.yaml
