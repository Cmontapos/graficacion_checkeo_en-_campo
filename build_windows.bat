@echo off
rem Genera dist\GasLab\GasLab.exe (ejecutar en Windows con Python 3.10+ en el PATH).
cd /d "%~dp0"
if not exist .venv python -m venv .venv || exit /b 1
.venv\Scripts\python -m pip install -r requirements-build.txt || exit /b 1
.venv\Scripts\python -m PyInstaller --noconfirm --clean GasLab.spec || exit /b 1
echo.
echo Listo: dist\GasLab\GasLab.exe
