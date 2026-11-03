#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]]; then
    echo 'Prepara el entorno siguiendo README.md: python3 -m venv .venv'
    exit 1
fi
# GasLab 2.0 en el navegador; la versión anterior (ventana Tkinter + visor Qt) sigue en graficar.py.
exec .venv/bin/python gaslab_web.py "$@"
