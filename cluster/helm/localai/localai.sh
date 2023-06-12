#!/bin/bash

helm repo add go-skynet https://go-skynet.github.io/helm-charts/
helm install local-ai go-skynet/local-ai -f values.yaml
