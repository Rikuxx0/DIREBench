#!/bin/sh
set -eu
if ! command -v k3d >/dev/null 2>&1; then echo 'k3d is required' >&2; exit 2; fi
if k3d cluster list -o json | python3 -c 'import json,sys; sys.exit(not any(x.get("name") == "direbench" for x in json.load(sys.stdin)))'; then
  echo 'Dedicated direbench cluster already exists'
else
  k3d cluster create direbench --image rancher/k3s:v1.31.5-k3s1 --servers 1 --agents 1 --k3s-arg '--disable=traefik@server:0'
fi
kubectl --context k3d-direbench cluster-info
