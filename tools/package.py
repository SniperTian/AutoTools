from pathlib import Path
import os
import zipfile
import sys

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

outputs = root / "outputs"
outputs.mkdir(exist_ok=True)
for source, archive, prefix in (
        (root, "AutoTools-source.zip", Path()),
        (outputs / "AutoTools-portable" / "AutoTools", "AutoTools-Windows-x64.zip", Path("AutoTools"))):
    if not source.is_dir():
        raise FileNotFoundError(f"Missing build directory: {source}")
    with zipfile.ZipFile(outputs / archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for folder, dirs, files in os.walk(source):
            dirs[:] = [d for d in dirs if d not in {"work", "outputs", "dist", ".git", "__pycache__", "data"}]
            for name in files:
                file = Path(folder) / name
                # Runtime ZIPs (especially base_library.zip) are essential.
                if file.suffix not in {".pyc", ".tmp"} and not (source == root and file.suffix == ".zip"):
                    z.write(file, prefix / file.relative_to(source))
    with zipfile.ZipFile(outputs / archive) as z:
        assert z.testzip() is None
        if source != root:
            required = {"AutoTools/AutoTools.exe", "AutoTools/_internal/python312.dll",
                        "AutoTools/_internal/base_library.zip"}
            if not required.issubset(z.namelist()):
                raise RuntimeError("Incomplete Python runtime in release archive")
            expected = {str(prefix / p.relative_to(source)).replace("\\", "/")
                        for p in source.rglob("*") if p.is_file() and "data" not in p.relative_to(source).parts
                        and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".tmp"}}
            if expected != set(z.namelist()):
                raise RuntimeError("Release archive differs from build directory")
        print(f"{archive}: {len(z.namelist())} files, {(outputs / archive).stat().st_size:,} bytes, CRC OK")
