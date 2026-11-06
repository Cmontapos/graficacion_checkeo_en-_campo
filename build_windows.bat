@echo off
rem Genera dist\GasLab\GasLab.exe (ejecutar en Windows con Python 3.10 a 3.14 de 64 bits de python.org en el PATH).
rem Al terminar (bien o con error) espera una tecla, para poder leer los mensajes al abrirlo con doble clic.
cd /d "%~dp0"

rem 1. Si ya hay un .venv, se comprueba que sirva en esta PC: que su python arranque y no venga de Microsoft Store
rem    (un .venv copiado de otra PC o de Linux no tiene Scripts\python.exe o apunta a un Python que no existe).
if exist .venv (
    .venv\Scripts\python -c "import sys; sys.exit(1 if 'WindowsApps' in sys.base_prefix else 0)" >nul 2>&1 || (
        echo El .venv no es valido para esta PC: se vuelve a crear.
        rmdir /s /q .venv
    )
)
rem    Un .venv hecho con un Python sin soporte (muy nuevo o de 32 bits) tambien se rehace.
if exist .venv (
    .venv\Scripts\python -c "import sys; v=sys.version_info[:2]; sys.exit(0 if (3,10)<=v<=(3,14) and sys.maxsize>2**32 else 1)" >nul 2>&1 || (
        echo El .venv usa una version de Python sin soporte: se vuelve a crear.
        rmdir /s /q .venv
    )
)

rem 2. Solo si hay que crear el .venv se necesita el Python del sistema, y no puede ser el de Microsoft Store
rem    (PyInstaller no puede copiar su python3XX.dll y el .exe no arranca).
if not exist .venv (
    where python >nul 2>&1 || goto :sin_python
    python -c "import sys; sys.exit(1 if 'WindowsApps' in sys.executable + sys.base_prefix else 0)" || goto :store
    python -c "import sys; v=sys.version_info[:2]; sys.exit(0 if (3,10)<=v<=(3,14) and sys.maxsize>2**32 else 1)" || goto :version
    python -m venv .venv || goto :error
)

.venv\Scripts\python -m pip install -r requirements-build.txt || goto :error
.venv\Scripts\python -m PyInstaller --noconfirm --clean GasLab.spec || goto :error

rem 3. Comprobacion: sin el DLL de Python el .exe falla con "Failed to load Python DLL ... python3XX.dll".
if not exist dist\GasLab\_internal\python3*.dll goto :sin_dll
if not exist dist\GasLab\_internal\web\index.html goto :sin_dll
echo.
echo Listo: dist\GasLab\GasLab.exe  (copia la carpeta dist\GasLab completa, no solo el .exe)
goto :fin

:sin_python
echo.
echo ERROR: no se encontro Python. Instala Python 3.11 desde https://www.python.org/downloads/
echo marcando "Add python.exe to PATH" y vuelve a ejecutar este archivo.
goto :fallo

:store
echo.
echo ERROR: el Python del PATH es el de Microsoft Store; con el el .exe no arranca (falta python3XX.dll).
echo Instala Python 3.11 desde https://www.python.org/downloads/ marcando "Add python.exe to PATH",
echo desactiva los alias "python.exe" en Configuracion ^> Aplicaciones ^> Alias de ejecucion de aplicaciones
echo y vuelve a ejecutar este archivo.
goto :fallo

:version
echo.
echo ERROR: este Python no sirve para compilar GasLab (pandas no tiene paquetes listos para el):
python -c "import sys, platform; print('   Python', platform.python_version(), platform.architecture()[0])"
echo Hace falta Python 3.10 a 3.14 de 64 bits. Instala Python 3.13 (Windows installer 64-bit) desde
echo https://www.python.org/downloads/ marcando "Add python.exe to PATH". Si dejas tambien el otro,
echo desinstalalo o ponlo despues en el PATH, y vuelve a ejecutar este archivo.
goto :fallo

:sin_dll
echo.
echo ERROR: la compilacion termino pero a dist\GasLab\_internal le falta el DLL de Python o la carpeta web.
echo Suele ser el antivirus (Defender) borrando archivos: revisa el historial de proteccion,
echo agrega una exclusion para esta carpeta y vuelve a ejecutar este archivo.
goto :fallo

:error
echo.
echo ERROR: el paso anterior fallo; el mensaje esta arriba.

:fallo
echo.
pause
exit /b 1

:fin
echo.
pause
exit /b 0
