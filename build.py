"""Optional packaging: install PyInstaller 6.17.0, then python build.py."""
from pathlib import Path
import subprocess
import sys

base = Path(__file__).resolve().parent
args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--onedir",
        "--name", "AutoTools", "--distpath", str(base / "outputs" / "AutoTools-portable"),
        "--workpath", str(base / "work" / "build-AutoTools"), "--specpath", str(base / "work"),
        "--icon", str(base / "assets" / "autotools.ico"),
        "--add-data", f"{base / 'assets'};assets"]
# Conda may have multiple Tk versions on PATH. Explicitly bundle this
# interpreter's DLLs, matching its Tcl/Tk script libraries.
for dll in ("tcl86t.dll", "tk86t.dll"):
    source = Path(sys.prefix) / "Library" / "bin" / dll
    if source.exists():
        args += ["--add-binary", f"{source};."]
args.append(str(base / "app.py"))
subprocess.run(args, cwd=base, check=True)
