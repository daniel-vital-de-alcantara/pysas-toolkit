"""Create a clean, self-contained Python UI ZIP (never package workspace data)."""
from pathlib import Path
import hashlib
import zipfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pysas_ui import VERSION

FILES = ["pysas.py", "pysas_ui.py", "ui_worker.py", "START_PYSAS.bat", "START_HERE.txt",
         "README.md", "LICENSE", "docs/scheduler-schema.md", "docs/ui-workbench.md",
         "examples/schedule_example.csv", "ui/index.html", "ui/app.js", "ui/style.css", "ui/icon.svg"]


def build(output=None):
    output = Path(output or ROOT / "release")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"PySAS-Workbench-Python-{VERSION}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in FILES:
            bundle.write(ROOT / name, "PySAS-Workbench/" + name)
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "SHA256SUMS.txt").write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
    print(archive)
    return archive


if __name__ == "__main__":
    build()
