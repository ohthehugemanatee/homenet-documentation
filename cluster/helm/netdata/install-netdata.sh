#!/bin/sh

helm repo add netdata https://netdata.github.io/helmchart/
helm install netdata netdata/netdata -f override.yaml

