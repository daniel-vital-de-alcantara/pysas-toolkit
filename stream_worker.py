"""One Run stream submission, through the independent engine only."""
from __future__ import annotations
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
from xml.etree import ElementTree as ET

from engine import run_sas
from ui_stream import combine_tables


def emit(event, **values):
    data = dict(event=event, time=time.time(), **values)
    path = os.environ.get("PYSAS_UI_EVENTS")
    if path:
        with open(path, "a", encoding="utf-8") as output:
            output.write(json.dumps(data, ensure_ascii=False) + "\n")
    else:
        print(json.dumps(data, ensure_ascii=False), flush=True)


def execute(folder, runner=run_sas):
    folder = Path(folder).resolve()
    plan = json.loads((folder / "stream-plan.json").read_text(encoding="utf-8"))
    document = plan["document"]
    started = time.time()
    status, errors, result = "FAILED", [], None
    cancel = folder / "_cancel.request"
    run_log = folder / "run.log"
    header = ["PySAS Run stream: " + document["name"], "Started: " + datetime.fromtimestamp(started, timezone.utc).isoformat(),
              "EGP: " + document["egp"]["name"], "Submitted as one SAS program, in this order:"]
    header.extend(f"  {s['position']}. {s['name']} · {s['scope']}" for s in plan["selections"])
    header += ["Source: source.sas · portable choices: stream.json", "", "--- SAS log ---", ""]
    run_log.write_text("\n".join(header), encoding="utf-8")
    print("\n".join(header[:-3]), flush=True)

    def save_status():
        elapsed = time.time() - started
        fields = dict(source=document["name"], status=status, started=datetime.fromtimestamp(started, timezone.utc).isoformat(), elapsed_seconds=elapsed)
        (folder / "status.txt").write_text("\n".join(f"{k}={v}" for k, v in fields.items()) + "\n", encoding="utf-8")
        return elapsed

    status = "RUNNING"; save_status()
    emit("start", key="stream", name=document["name"], kind="stream", path=str(folder), estimate=plan["estimate"])
    finished = threading.Event()

    def stages():
        last = ""
        control = os.environ.get("PYSAS_UI_CONTROL_FILE")
        while not finished.wait(.2):
            try:
                if control and Path(control).is_file(): cancel.touch(exist_ok=True)
                phase = ET.parse(folder / "execution/_automation.xml").getroot().get("phase", "")
                if phase and phase != last:
                    last = phase
                    print("Enterprise Guide · " + phase, flush=True)
                    emit("progress", key="stream", phase=phase, progress="Enterprise Guide · " + phase)
            except (OSError, ET.ParseError): pass

    thread = threading.Thread(target=stages, daemon=True); thread.start()
    try:
        control = os.environ.get("PYSAS_UI_CONTROL_FILE")
        if cancel.is_file() or (control and Path(control).is_file()):
            status = "CANCELLED"; errors.append("Cancelled before SAS started.")
        else:
            result = runner(folder / document["egp"]["path"], folder / "source.sas", folder / "execution",
                            export_html=document["export_html"], export_tables=document["export_tables"],
                            table_format="xlsx", server_program=document["server_program"] or None, cancel_file=cancel)
            status = result.status; errors.extend(result.errors)
            with run_log.open("a", encoding="utf-8") as output:
                output.write(result.log)
            if document["export_tables"] and document["consolidate_tables"] and result.table_files and status != "CANCELLED":
                emit("progress", key="stream", phase="combining tables", progress="Combining exported tables into tables.xlsx")
                try:
                    mapping = combine_tables(result.table_files, folder / "tables.xlsx")
                    (folder / "tables-index.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception as exc:
                    errors.append("Table consolidation failed; individual exports retained: " + str(exc))
                    if status == "SUCCESS": status = "EXPORT_ERROR"
    except Exception as exc:
        status = "FAILED"; errors.append(str(exc)); traceback.print_exc()
    finally:
        finished.set(); thread.join(timeout=2)
    elapsed = save_status()
    with run_log.open("a", encoding="utf-8") as output:
        output.write("\n\n--- Stream result ---\n" + status + f" · {elapsed:.1f} seconds\n")
        for message in errors: output.write("ERROR: " + message + "\n")
    record = dict(status=status, fingerprint=plan["fingerprint"], elapsed_seconds=elapsed, errors=errors,
                  warnings=list(result.warnings) if result else [], selections=plan["selections"],
                  html_files=[str(p.relative_to(folder)) for p in result.html_files] if result else [],
                  table_files=[str(p.relative_to(folder)) for p in result.table_files] if result else [],
                  combined_tables="tables.xlsx" if (folder / "tables.xlsx").is_file() else None)
    (folder / "stream-result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    message = "; ".join(errors) or "Complete. Inspect the source, SAS log and outputs."
    emit("finish", key="stream", name=document["name"], path=str(folder), status=status, elapsed=elapsed, message=message)
    emit("stream-result", path=str(folder), status=status, elapsed=elapsed, message=message)
    return 0 if status == "SUCCESS" else 130 if status == "CANCELLED" else 1


if __name__ == "__main__":
    try: sys.exit(execute(sys.argv[1]))
    except Exception:
        traceback.print_exc(); sys.exit(1)
