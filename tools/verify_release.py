"""Extract the actual published ZIP and start its frozen runtime/Tk diagnostic."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import time
import zipfile

root = Path(__file__).resolve().parents[1]
archive = root / "outputs" / "AutoTools-Windows-x64.zip"
destination = root / "work" / f"release-check-{time.time_ns()}"
with zipfile.ZipFile(archive) as package:
    assert package.testzip() is None
    package.extractall(destination)
    for member in package.infolist():
        if not member.is_dir():
            assert (destination / member.filename).read_bytes() == package.read(member)
report = destination / "startup.json"
env = dict(os.environ)
for key in list(env):
    if key.upper().startswith(("PYTHON", "CONDA")):
        env.pop(key)
env["PATH"] = os.path.join(env.get("SystemRoot", r"C:\Windows"), "System32")
exe = destination / "AutoTools" / "AutoTools.exe"
subprocess.run([str(exe), "--startup-check", str(report)], cwd=destination,
               env=env, check=True, timeout=30)
result = json.loads(report.read_text(encoding="utf-8"))
assert result["ok"] and result["frozen"] and result["icon_width"] > 0
print(json.dumps({"archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                  "extracted_exe": str(exe), "startup": result}, ensure_ascii=False, indent=2))
