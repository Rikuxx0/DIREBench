#!/bin/sh
set -eu
if ! command -v k3d >/dev/null 2>&1; then echo 'k3d is required' >&2; exit 2; fi
k3d cluster delete direbench
