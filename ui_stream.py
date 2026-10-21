"""Ordered source composition and portable Run stream documents.

Only stream_worker invokes engine.py. Validation/export/estimation never run SAS.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import uuid

from engine import _decode
from pysas import select_graph_text
from ui_data import estimate_task

FORMAT = "pysas-run-stream-1"
JSON_LIMIT = 128 * 1024**2
SOURCE_LIMIT = 16 * 1024**2
EGP_LIMIT = 64 * 1024**2
COMPILED_LIMIT = 64 * 1024**2


def label(value, default="", limit=120):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f"Use a name of up to {limit} characters without control characters.")
    return value.strip() or default


def file_ref(value, suffix):
    if value is None: return None
    if not isinstance(value, dict) or not isinstance(value.get("path"), str) or not value["path"]:
        raise ValueError("Invalid stream file reference.")
    name = label(value.get("name", ""), Path(value["path"]).name, 200)
    if Path(name).name != name or re.search(r'[\\<>:"|?*]', name) or Path(name).suffix.lower() != suffix:
        raise ValueError("Choose a " + suffix + " file.")
    digest = value.get("sha256", "")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Stream source is missing its checksum. Choose the file again.")
    return dict(path=value["path"], name=name, sha256=digest)


def validate(value):
    if not isinstance(value, dict) or value.get("format") != FORMAT:
        raise ValueError("Choose a Run stream JSON exported by PySAS.")
    rows = value.get("rows")
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("A stream can contain up to 1,000 rows.")
    result = dict(format=FORMAT, name=label(value.get("name", ""), "Untitled stream"),
                  egp=file_ref(value.get("egp"), ".egp"), server_program=label(value.get("server_program", "")), rows=[])
    for key, default in (("export_html", True), ("export_tables", False), ("consolidate_tables", False)):
        setting = value.get(key, default)
        if type(setting) is not bool: raise ValueError(key + " must be a checkbox value.")
        result[key] = setting
    ids = set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict): raise ValueError("Invalid stream row.")
        identifier = row.get("id")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", identifier) or identifier in ids:
            raise ValueError("Each stream row needs a unique ID.")
        ids.add(identifier)
        mode = row.get("mode", "whole")
        if mode not in {"whole", "lines", "section"}: raise ValueError("Choose whole file, lines or section.")
        bounds = {}
        for key in ("row_start", "row_end"):
            number = row.get(key)
            if number is not None and (type(number) is not int or not 1 <= number <= 100000000):
                raise ValueError(f"Row {index}: line numbers must be positive whole numbers or blank.")
            bounds[key] = number
        if mode == "lines" and bounds["row_start"] and bounds["row_end"] and bounds["row_start"] > bounds["row_end"]:
            raise ValueError(f"Row {index}: the first line is after the last line.")
        result["rows"].append(dict(id=identifier, file=file_ref(row.get("file"), ".sas"), mode=mode,
                                   section=label(row.get("section", ""), limit=200), **bounds))
    return result


def describe(app, path, name=None):
    path = app.input_path(str(path))
    suffix = path.suffix.lower()
    if suffix not in {".sas", ".egp"} or not path.is_file() or path.is_symlink():
        raise ValueError("Choose an existing SAS or EGP file.")
    if path.stat().st_size > (SOURCE_LIMIT if suffix == ".sas" else EGP_LIMIT):
        raise ValueError("Run stream accepts SAS files up to 16 MB and EGP templates up to 64 MB.")
    raw = path.read_bytes()
    result = dict(path=app.relative(path), name=name or path.name, sha256=hashlib.sha256(raw).hexdigest())
    if suffix == ".sas":
        text = _decode(raw)
        result.update(lines=len(text.replace("\r\n", "\n").replace("\r", "\n").splitlines()),
                      sections=list(dict.fromkeys(re.findall(r"(?mi)^\s*\* \(please do not delete\) section_start: (.+?);\s*$", text))))
    return result


def read_asset(app, ref, suffix):
    path = app.input_path(ref["path"])
    if not path.is_file() or path.suffix.lower() != suffix or path.stat().st_size > (SOURCE_LIMIT if suffix == ".sas" else EGP_LIMIT):
        raise ValueError(ref["name"] + ": source is missing or too large. Choose the file again.")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise ValueError(ref["name"] + ": source changed. Choose it again to review the new version.")
    return raw


def assets(app, document):
    result = {}
    for ref, suffix in [(document["egp"], ".egp"), *((row["file"], ".sas") for row in document["rows"])]:
        if ref is not None and ref["sha256"] not in result:
            result[ref["sha256"]] = read_asset(app, ref, suffix)
    sas_size = sum(len(raw) for digest, raw in result.items() if not document["egp"] or digest != document["egp"]["sha256"])
    if sas_size > SOURCE_LIMIT: raise ValueError("The stream's distinct SAS files exceed 16 MB in total.")
    return result


def compose(app, value, *, require_egp=False):
    document = validate(value)
    if require_egp and not document["egp"]: raise ValueError("Choose the connection EGP first.")
    if not document["rows"]: raise ValueError("Add at least one SAS file.")
    raw_assets = assets(app, document)
    chunks, selections, compiled_size = [], [], 0
    for index, row in enumerate(document["rows"], 1):
        ref = row["file"]
        if not ref: raise ValueError(f"Row {index}: choose a SAS file.")
        text = _decode(raw_assets[ref["sha256"]])
        selection = dict(name=ref["name"], section=row["section"] if row["mode"] == "section" else "",
                         row_start=row["row_start"] if row["mode"] == "lines" else None,
                         row_end=row["row_end"] if row["mode"] == "lines" else None)
        if row["mode"] == "section" and not row["section"]: raise ValueError(f"Row {index}: enter a section name.")
        selected = select_graph_text(text, selection)
        if not selected.strip(): raise ValueError(f"Row {index}: the selected code is empty.")
        scope = "Section " + row["section"] if row["mode"] == "section" else f"Lines {row['row_start'] or 1}–{row['row_end'] or 'end'}" if row["mode"] == "lines" else "Whole file"
        # Comments are informational only; never let a filename close a SAS comment.
        caption = (ref["name"] + " · " + scope).replace("*/", "* /")
        chunk = f"/* PySAS stream row {index}: {caption} */\n{selected}\n\n"
        compiled_size += len(chunk.encode("utf-8"))
        if compiled_size > COMPILED_LIMIT: raise ValueError("Selected code exceeds 64 MB. Split it into smaller streams.")
        chunks.append(chunk)
        selections.append(dict(id=row["id"], position=index, **selection, scope=scope,
                               sha256=hashlib.sha256(selected.encode("utf-8")).hexdigest()))
    fingerprint = hashlib.sha256(json.dumps(dict(parts=[s["sha256"] for s in selections], egp=document["egp"]["sha256"] if document["egp"] else None,
                     server=document["server_program"], html=document["export_html"], tables=document["export_tables"], consolidate=document["consolidate_tables"]), sort_keys=True).encode()).hexdigest()
    return dict(document=document, source="".join(chunks), selections=selections, fingerprint=fingerprint, assets=raw_assets)


def portable(document, raw_assets):
    return {**document, "assets": {digest: base64.b64encode(raw).decode("ascii") for digest, raw in raw_assets.items()}}


def artifact(app, value, kind):
    if kind == "source":
        plan = compose(app, value)
        raw = plan["source"].encode("utf-8"); extension = ".sas"; document = plan["document"]
    else:
        document = validate(value)
        raw = json.dumps(portable(document, assets(app, document)), ensure_ascii=False, indent=2).encode("utf-8")
        extension = ".json"
        if len(raw) > JSON_LIMIT: raise ValueError("Portable stream JSON exceeds 128 MB.")
    with app.lock:
        if app.storage_busy: raise ValueError("Wait for the saved-data operation to finish.")
        folder = app.storage / "artifacts" / uuid.uuid4().hex
        folder.mkdir(parents=True)
        stem = re.sub(r"[^a-zA-Z0-9_-]", "_", document["name"])[:80] or "stream"
        path = folder / (stem + extension)
        path.write_bytes(raw)
    return dict(path=app.relative(path), bytes=len(raw))


def import_document(app, raw):
    if len(raw) > JSON_LIMIT: raise ValueError("Run stream JSON exceeds 128 MB.")
    value = json.loads(raw.decode("utf-8-sig"))
    document = validate(value)
    encoded = value.get("assets")
    if not isinstance(encoded, dict): raise ValueError("Portable stream JSON is missing its embedded files.")
    decoded, total_sas = {}, 0
    for ref, suffix in [(document["egp"], ".egp"), *((r["file"], ".sas") for r in document["rows"])]:
        if ref is None or ref["sha256"] in decoded: continue
        content = encoded.get(ref["sha256"])
        if not isinstance(content, str): raise ValueError(ref["name"] + ": embedded file is missing.")
        try: payload = base64.b64decode(content, validate=True)
        except (ValueError, binascii.Error) as exc: raise ValueError("Invalid embedded stream file.") from exc
        if len(payload) > (SOURCE_LIMIT if suffix == ".sas" else EGP_LIMIT) or hashlib.sha256(payload).hexdigest() != ref["sha256"]:
            raise ValueError(ref["name"] + ": embedded file is too large or its checksum is invalid.")
        if suffix == ".sas":
            _decode(payload); total_sas += len(payload)
        decoded[ref["sha256"]] = (payload, suffix)
    if total_sas > SOURCE_LIMIT: raise ValueError("The stream's distinct SAS files exceed 16 MB in total.")
    # No output is created until the entire document has passed validation.
    with app.lock:
        if app.storage_busy: raise ValueError("Wait for the saved-data operation to finish.")
        folder = app.tasks / "stream-sources"; folder.mkdir(exist_ok=True)
        paths, written = {}, []
        try:
            for digest, (payload, suffix) in decoded.items():
                path = folder / (uuid.uuid4().hex + suffix); path.write_bytes(payload); written.append(path)
                paths[digest] = app.relative(path)
            for ref in [document["egp"], *(r["file"] for r in document["rows"])]:
                if ref:
                    ref["path"] = paths[ref["sha256"]]
                    if Path(ref["name"]).suffix.lower() == ".sas":
                        ref.update(describe(app, ref["path"], ref["name"]))
        except BaseException:
            for path in written: path.unlink(missing_ok=True)
            raise
    return document


def estimate(app, value, plan=None):
    plan = plan or compose(app, value)
    matches = []
    for parent, _ in app.run_bases():
        if not parent.is_dir(): continue
        for folder in parent.iterdir():
            record = folder / "stream-result.json"
            if folder.is_symlink() or not record.is_file(): continue
            try:
                data = json.loads(record.read_text(encoding="utf-8"))
                seconds = data.get("elapsed_seconds")
                if data.get("status") == "SUCCESS" and data.get("fingerprint") == plan["fingerprint"] and type(seconds) in (int, float) and math.isfinite(seconds) and seconds > 0:
                    matches.append((record.stat().st_mtime, seconds))
            except (OSError, ValueError): continue
    if matches:
        values = [seconds for _, seconds in sorted(matches, reverse=True)[:10]]
        return dict(seconds=statistics.median(values), samples=len(values), unknown=0, basis="Same selected code, order, EGP and output options; recent successful streams.")
    samples = app.timing_samples()
    rows = [estimate_task(s, samples) for s in plan["selections"]]
    known = [row["seconds"] for row in rows if row["seconds"] is not None]
    unknown = len(rows) - len(known)
    return dict(seconds=sum(known) if known else None, samples=sum(row["samples"] for row in rows), unknown=unknown,
                basis="Sum of comparable program/section/line timings from previous runs. A + is a partial estimate; a single SAS session and data changes can affect duration.")


def prepare(app, value):
    plan = compose(app, value, require_egp=True)
    if plan["document"]["export_tables"] and plan["document"]["consolidate_tables"]:
        import importlib.util
        if importlib.util.find_spec("openpyxl") is None: raise ValueError("Install openpyxl to combine tables into one workbook.")
    forecast = estimate(app, value, plan)
    folder = app.tasks / "files" / (datetime.now().strftime("%Y%m%d_%H%M%S") + "__stream_" + uuid.uuid4().hex[:8])
    folder.mkdir(parents=True)
    try:
        (folder / "source.sas").write_text(plan["source"], encoding="utf-8", newline="")
        doc = json.loads(json.dumps(plan["document"]))
        source_dir = folder / "sources"; source_dir.mkdir()
        for index, ref in enumerate([doc["egp"], *(r["file"] for r in doc["rows"])], 1):
            path = source_dir / (str(index).zfill(3) + "__" + ref["name"])
            path.write_bytes(plan["assets"][ref["sha256"]])
            ref["path"] = str(path.relative_to(folder)).replace("\\", "/")
        (folder / "stream.json").write_text(json.dumps(portable(doc, plan["assets"]), ensure_ascii=False, indent=2), encoding="utf-8")
        manifest = dict(fingerprint=plan["fingerprint"], selections=plan["selections"], estimate=forecast, document=doc)
        (folder / "stream-plan.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    except BaseException:
        import shutil
        shutil.rmtree(folder)
        raise
    return folder, plan["document"], forecast


def combine_tables(paths, destination):
    """Stream workbook cells to one file; retain original exports on any failure."""
    from openpyxl import load_workbook, Workbook
    from openpyxl.cell import WriteOnlyCell
    workbook = Workbook(write_only=True)
    used, sheets = set(), []
    temporary = destination.with_suffix(".tmp.xlsx")
    try:
        for path in paths:
            source = load_workbook(path, read_only=True, data_only=False)
            try:
                for sheet in source.worksheets:
                    stem = re.sub(r"[\\/*?:\[\]]", "_", path.stem + ("_" + sheet.title if len(source.worksheets) > 1 else ""))[:31] or "Table"
                    name, n = stem, 1
                    while name.casefold() in used:
                        n += 1; name = stem[:31-len(str(n))-1] + "_" + str(n)
                    used.add(name.casefold()); target = workbook.create_sheet(name); sheets.append(dict(file=path.name, sheet=sheet.title, combined_sheet=name))
                    for row in sheet.iter_rows():
                        cells = []
                        for cell in row:
                            copied = WriteOnlyCell(target, value=cell.value)
                            if cell.data_type == "s": copied.data_type = "s"
                            copied.number_format = cell.number_format; cells.append(copied)
                        target.append(cells)
            finally: source.close()
        if not sheets: return []
        workbook.save(temporary); temporary.replace(destination)
        return sheets
    finally:
        workbook.close(); temporary.unlink(missing_ok=True)
