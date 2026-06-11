# PyInstaller spec for FlowDesk (PRD §11 M6).
# Build:  uv run pyinstaller flowdesk.spec --noconfirm
# Output: dist/FlowDesk/ (onedir; VTK dominates the size - NFR target <= 600 MB)

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

a = Analysis(
    ["launcher.py"],
    pathex=["src"],
    binaries=[],
    datas=[
        ("src/flowdesk/ui/assets", "flowdesk/ui/assets"),
        ("src/flowdesk/exec/error_explanations.yaml", "flowdesk/exec"),
        ("LICENSE", "."),
    ],
    hiddenimports=[
        "flowdesk.ui.main",
        "vtkmodules.all",
        "vtkmodules.util.data_model",
        "vtkmodules.util.execution_model",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # NFR §9: keep the installer lean - none of these are used
        "matplotlib.tests", "numpy.tests",
        "tkinter", "IPython", "jupyter",
        "PyQt6.QtBluetooth", "PyQt6.QtDBus", "PyQt6.Qtdesigner",
        "PyQt6.QtNetworkAuth", "PyQt6.QtNfc", "PyQt6.QtQml",
        "PyQt6.QtQuick", "PyQt6.QtSensors", "PyQt6.QtSerialPort",
        "PyQt6.QtSql", "PyQt6.QtTest", "PyQt6.QtWebChannel",
        "PyQt6.QtWebSockets", "PyQt6.QtXml",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FlowDesk",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="FlowDesk",
)
