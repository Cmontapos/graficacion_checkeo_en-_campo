# PyInstaller: pyinstaller --noconfirm GasLab.spec  ->  dist/GasLab/GasLab.exe con GasLab 2.0 (gaslab_web.py).
# Sin consola: abre su propia ventana (Edge o Chrome en modo app) y se cierra al cerrarla. La versión 1 queda en graficar.py.
from PyInstaller.utils.hooks import collect_data_files

datas = [('web', 'web')]
for pkg in ('plotly', 'tzdata'):
    datas += collect_data_files(pkg)

a = Analysis(
    ['gaslab_web.py'],
    pathex=[],
    datas=datas,
    hiddenimports=['tzdata', 'PIL.TiffImagePlugin', 'openpyxl'],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'pyqtgraph', 'folium', 'tkinter', 'matplotlib', 'IPython', 'pytest'],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='GasLab', console=False, icon='gaslab.ico')
coll = COLLECT(exe, a.binaries, a.datas, name='GasLab')
