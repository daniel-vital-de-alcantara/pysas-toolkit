"""Test-only process substitute for the new engine's Windows/EG worker."""
import json
from pathlib import Path
import subprocess
import sys
import time
from xml.etree import ElementTree as ET
import zipfile

request_path = Path(sys.argv[1])
root = request_path.parent
request = json.loads(request_path.read_text(encoding="utf-8"))
config = json.loads(Path(request["egp_path"]).read_text(encoding="utf-8"))
(root / "observed.json").write_text(json.dumps(dict(request=request, text=(root / "submitted.sas").read_bytes().decode("utf-8"))), encoding="utf-8")
if config.get("change_source"):
    Path(request["sas_path"]).write_text("changed after submission;", encoding="utf-8")
if config.get("delay"):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    (root / "child.pid").write_text(str(child.pid))
    (root / "sas.log").write_text("NOTE: started before timeout", encoding="utf-8")
    time.sleep(config["delay"])
if config.get("output_bytes"):
    sys.stdout.write("x" * config["output_bytes"])
if not config.get("no_log"):
    (root / "sas.log").write_bytes(config.get("log", "NOTE: completed café\n").encode(config.get("log_encoding", "utf-8")))
(root / "console.txt").write_bytes("Automation console: café\n".encode("utf-16-le"))
report = ET.Element("run", complete=str(config.get("complete", "1")), ran="1", server="SASApp")
if config.get("error"):
    ET.SubElement(report, "error", phase="running").text = config["error"]
if request["export_html"]:
    for i in range(config.get("html_count", 1)):
        folder = root / "html" / str(i)
        folder.mkdir()
        (folder / "plot.png").write_bytes(b"fake plot asset")
        html = config.get("html", '<!doctype html><html><body>café<img src="plot.png"></body></html>')
        (folder / "index.html").write_bytes(html.encode(config.get("html_encoding", "utf-8")))
        ET.SubElement(report, "output", kind="html", path=f"html/{i}/index.html")
if request["export_tables"]:
    for i in range(config.get("table_count", 2)):
        if config.get("failed_table") == i:
            ET.SubElement(report, "export-error", phase="table").text = f"table {i}: Access denied"
            continue
        path = root / "tables" / (str(i) + "." + request["table_format"])
        if config.get("bad_xlsx"):
            path.write_bytes(b"not a workbook")
        elif request["table_format"] == "xlsx":
            with zipfile.ZipFile(path, "w") as workbook:
                workbook.writestr("xl/workbook.xml", "<workbook/>")
        else:
            path.write_text('id,name\n1,café\n', encoding="utf-8")
        ET.SubElement(report, "output", kind="table", path=path.relative_to(root).as_posix())
if config.get("outside_path"):
    ET.SubElement(report, "output", kind="table", path=config["outside_path"])
if not config.get("no_manifest"):
    (root / "_automation.xml").write_bytes(b"<unfinished" if config.get("broken_manifest") else ET.tostring(report))
sys.exit(config.get("returncode", 0))
