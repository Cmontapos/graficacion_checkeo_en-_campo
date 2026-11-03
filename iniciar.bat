@echo off
rem GasLab 2.0 desde el codigo fuente, en su propia ventana (el .venv se prepara como dice README.md).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Prepara el entorno siguiendo README.md: python -m venv .venv
    pause
    exit /b 1
)
.venv\Scripts\python gaslab_web.py --ventana %*
