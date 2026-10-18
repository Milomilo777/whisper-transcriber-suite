#!/usr/bin/env bash
set -euo pipefail
# Provisioning is explicit; this wrapper has the same behavior as setup.py --all.
python3 "$(dirname "$0")/setup.py" --all "$@"
