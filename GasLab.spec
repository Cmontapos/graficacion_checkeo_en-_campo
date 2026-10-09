# PyInstaller: pyinstaller --noconfirm GasLab.spec
from PyInstaller.utils.hooks import collect_data_files

datas = [('visor_template.html', '.')]
for pkg in ('plotly', 'folium', 'branca', 'xyzservices', 'tzdata', 'pyqtgraph'):
    datas += collect_data_files(pkg)

a = Analysis(
    ['graficar.py'],
    pathex=[],
    datas=datas,
    hiddenimports=['tzdata', 'visor_qt', 'PIL', 'requests'],
    excludes=['PyQt6', 'PySide2', 'PySide6', 'matplotlib', 'IPython', 'pytest'],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='GasLab', console=False)
coll = COLLECT(exe, a.binaries, a.datas, name='GasLab')
