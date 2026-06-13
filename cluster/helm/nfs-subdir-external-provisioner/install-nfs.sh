#!/bin/bash
helm repo add nfs-subdir-external-provisioner https://kubernetes-sigs.github.io/nfs-subdir-external-provisioner/

helm upgrade nfs-subdir-external-provisioner nfs-subdir-external-provisioner/nfs-subdir-external-provisioner \
  --set nfs.server=shoebox.vert \
  --set nfs.path=/export/configs/kubernetes \
  --namespace kube-system

# All done! Show storageclasses
k get storageclass

