#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]]; then
    echo 'Prepara el entorno siguiendo README.md: python3 -m venv .venv'
    exit 1
fi
exec .venv/bin/python graficar.py "$@"
