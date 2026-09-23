#!/usr/bin/env python3
"""PySAS 0.3.11 — portable SAS Enterprise Guide command-line utilities.

Keep this file beside the EGP, scheduler workbook and any top-level _*.sas
initialisation files it should use.  Python 3.9+ is recommended.  ``rich`` is
optional; ``openpyxl`` is required only for scheduler and table-workbook work.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from xml.etree import ElementTree as ET


VERSION = "0.3.12"
ROOT_DIR = Path(__file__).resolve().parent
CODEBASE_FILE = "codebase.sasbundle.txt"
BACKUP_FOLDER = "_codebase_backups"
FORMAT_VERSION = 1
BUNDLE_START = "/*@@SAS_BUNDLE_START@@"
BUNDLE_END = "@@SAS_BUNDLE_END@@*/"
FILE_START = "/*@@SAS_FILE_START@@"
FILE_END = "@@SAS_FILE_END@@*/"
FOOTER_START = "/*@@SAS_BUNDLE_FOOTER@@"
FOOTER_END = "@@SAS_BUNDLE_FOOTER_END@@*/"
REQUIRED_COLUMNS = {
    "task_id", "program", "depends_on", "skip", "row_start", "row_end",
    "section", "stop_process_on_error", "stop_program_on_error",
    "max_parallel", "always_run",
}
FINAL_OK = {"SUCCESS", "SKIPPED_SUCCESS", "SKIPPED_PREVIOUS", "ALWAYS_RUN_DEFINITION"}
CONNECTION_PATTERNS = (
    "the connection to the server has been lost",
    "unable to communicate with the server",
    "server is disconnected",
    "rpc_e_disconnected",
    "remote object has been lost",
    "wrapperlostexception",
    "object invoked has disconnected",
)
PRINT_LOCK = threading.Lock()


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def text_encoding(raw: bytes) -> str:
    """Only treat text as UTF-16 when its BOM or NUL layout supports it."""
    if raw.startswith(b"\x00MSMAMARPCRYPT"):
        raise ValueError("This file is encrypted/protected (MSMAMARPCRYPT), not readable source text. Use a readable copy from an application authorized to open it.")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    sample = raw[:4096]
    if len(sample) >= 4:
        even, odd = sample[::2], sample[1::2]
        if odd.count(0) / len(odd) > .3 and even.count(0) / len(even) < .1:
            return "utf-16-le"
        if even.count(0) / len(even) > .3 and odd.count(0) / len(odd) < .1:
            return "utf-16-be"
    import codecs
    try:
        codecs.getincrementaldecoder("utf-8-sig")().decode(raw, final=False)
        return "utf-8-sig"
    except UnicodeDecodeError:
        return "cp1252"


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    return raw.decode(text_encoding(raw), errors="replace")


def normalized(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"


def safe_name(value: str, limit: int = 70) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-") or "item"
    return value[:limit]


def truthy(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"1", "1.0", "true", "yes", "y", "x"}


def require_openpyxl():
    try:
        from openpyxl import Workbook, load_workbook
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
        return Workbook, load_workbook, Font, PatternFill, get_column_letter
    except ImportError as exc:
        raise RuntimeError("This command needs openpyxl: py -m pip install openpyxl") from exc


def find_one(pattern: str, description: str, folder: Path = ROOT_DIR) -> Path:
    items = sorted(p for p in folder.glob(pattern) if p.is_file() and not p.name.startswith("~$"))
    if not items:
        raise FileNotFoundError(f"No {description} found beside {Path(__file__).name}")
    if len(items) != 1:
        raise RuntimeError(f"Multiple {description}s found: " + ", ".join(p.name for p in items))
    return items[0]


def sas_files(folder: Path) -> list[Path]:
    """Find SAS files without depending on the filesystem's case sensitivity."""
    return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.casefold() == ".sas"),
                  key=lambda p: (p.name.casefold(), p.name)) if folder.is_dir() else []


def init_files(explicit: Path | None = None, folder: Path | None = None, extra_folder: Path | None = None) -> list[Path]:
    if explicit:
        if not explicit.is_file():
            raise FileNotFoundError(explicit)
        return [explicit]
    folders = [folder or ROOT_DIR]
    if extra_folder is not None:
        folders.append(extra_folder)
    paths = {p.resolve() for directory in folders for p in sas_files(directory) if p.name.startswith("_")}
    return sorted(paths, key=lambda p: (p.name.casefold(), str(p).casefold()))


def print_home() -> None:
    inits = init_files()
    egps = sorted(ROOT_DIR.glob("*.egp"))
    excels = sorted(p for p in ROOT_DIR.glob("*.xlsx") if not p.name.startswith("~$"))
    print(f"PySAS {VERSION}")
    print("SAS Enterprise Guide command-line utilities\n")
    print(f"Folder: {ROOT_DIR}")
    print(f"EGP projects: {len(egps)} | Excel workbooks: {len(excels)} | SAS files: {len(list(ROOT_DIR.glob('*.sas')))}")
    names = ", ".join(p.name for p in inits) if inits else "none"
    print(f"Runner init: {len(inits)} _*.sas file(s) ({names})")
    print("\nRunner convention:")
    print("  All _*.sas files beside pysas.py run first, alphabetically.")
    print("  A job named foo.tables.sas automatically exports all output datasets.")
    print("\nCommon commands:")
    print("  py pysas.py runner watch")
    print("  py pysas.py runner run diagnostic.sas")
    print("  py pysas.py schedule")
    print("  py pysas.py egp inspect")
    print("  py pysas.py bundle pack")
    print("  py pysas.py --help")


# ---------------------------------------------------------------------------
# Bundle engine
# ---------------------------------------------------------------------------


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def marker(prefix: str, data: dict[str, Any], suffix: str) -> str:
    return f"{prefix} {json.dumps(data, ensure_ascii=False, sort_keys=True)} {suffix}\n"


def discover_sas(recursive: bool, root: Path = ROOT_DIR) -> list[Path]:
    paths = root.glob("**/*.sas" if recursive else "*.sas")
    backup = (root / BACKUP_FOLDER).resolve()
    result = []
    for path in paths:
        if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            continue
        try:
            path.resolve().relative_to(backup)
            continue
        except ValueError:
            result.append(path)
    return sorted(result, key=lambda p: p.relative_to(root).as_posix().casefold())


def bundle_root(args: argparse.Namespace) -> Path:
    value = getattr(args, "root", None)
    root = Path(value).expanduser().resolve() if value else ROOT_DIR
    if not root.is_dir():
        raise ValueError(f"Code folder does not exist: {root}")
    return root


def bundle_target(root: Path, relative: str) -> Path:
    target = root.joinpath(*PurePosixPath(relative).parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Bundle path escapes the code folder: {relative}")
    return target


def bundle_pack(args: argparse.Namespace) -> int:
    root = bundle_root(args)
    paths = discover_sas(args.recursive, root)
    if not paths:
        raise ValueError("No SAS files found")
    hashes: list[str] = []
    chunks = [marker(BUNDLE_START, {
        "format": "sas-codebase-bundle", "version": FORMAT_VERSION,
        "generated_utc": utc_now(), "root_name": root.name,
        "recursive": bool(args.recursive), "file_count": len(paths),
    }, BUNDLE_END), "\n"]
    for path in paths:
        content = normalized(read_text(path))
        digest = sha256_text(content)
        hashes.append(digest)
        rel = path.relative_to(root).as_posix()
        chunks += [marker(FILE_START, {"path": rel, "sha256": digest, "chars": len(content)}, FILE_END),
                   content, f"{FILE_END}\n\n"]
    chunks.append(marker(FOOTER_START, {
        "file_count": len(paths), "manifest_sha256": sha256_text("".join(hashes)),
    }, FOOTER_END))
    output = root / (args.output or CODEBASE_FILE)
    output.write_text("".join(chunks), encoding="utf-8", newline="\n")
    print(f"Packed {len(paths)} SAS file(s): {output}")
    return 0


def parse_marker(line: str, prefix: str, suffix: str) -> dict[str, Any]:
    if not line.startswith(prefix) or not line.rstrip("\r\n").endswith(suffix):
        raise ValueError(f"Invalid bundle marker: expected {prefix}")
    raw = line[len(prefix): line.rfind(suffix)].strip()
    return json.loads(raw)


def parse_bundle(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    if not lines:
        raise ValueError("Bundle is empty")
    header = parse_marker(lines[0], BUNDLE_START, BUNDLE_END)
    files: list[dict[str, Any]] = []
    footer: dict[str, Any] | None = None
    i = 1
    while i < len(lines):
        line = lines[i]
        if line.startswith(FILE_START):
            meta = parse_marker(line, FILE_START, FILE_END)
            i += 1
            body: list[str] = []
            while i < len(lines) and lines[i].rstrip("\r\n") != FILE_END:
                body.append(lines[i]); i += 1
            if i >= len(lines):
                raise ValueError(f"Unclosed file block: {meta.get('path')}")
            files.append({"meta": meta, "content": normalized("".join(body))})
        elif line.startswith(FOOTER_START):
            footer = parse_marker(line, FOOTER_START, FOOTER_END)
        i += 1
    if footer is None:
        raise ValueError("Bundle footer is missing")
    return header, files, footer


def validate_bundle(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    header, files, footer = parse_bundle(path)
    errors: list[str] = []
    if header.get("format") != "sas-codebase-bundle" or header.get("version") != FORMAT_VERSION:
        errors.append("Unsupported header format/version")
    names: set[str] = set(); digests: list[str] = []
    for item in files:
        meta, content = item["meta"], item["content"]
        rel = str(meta.get("path", "")); pp = PurePosixPath(rel)
        if not rel or pp.is_absolute() or ".." in pp.parts:
            errors.append(f"Unsafe path: {rel!r}")
        key = rel.casefold()
        if key in names: errors.append(f"Duplicate path: {rel}")
        names.add(key)
        digest = sha256_text(content); digests.append(digest)
        if digest != meta.get("sha256"):
            item["edited"] = True
        else:
            item["edited"] = False
    if int(footer.get("file_count", -1)) != len(files):
        errors.append("Footer file count mismatch")
    original_manifest = sha256_text("".join(str(i["meta"].get("sha256", "")) for i in files))
    if footer.get("manifest_sha256") != original_manifest:
        errors.append("Footer manifest checksum mismatch")
    return files, errors


def bundle_verify(args: argparse.Namespace) -> int:
    root = bundle_root(args)
    path = root / (args.bundle or CODEBASE_FILE)
    files, errors = validate_bundle(path)
    edited = sum(bool(i["edited"]) for i in files)
    identical = different = missing = 0
    for item in files:
        target = bundle_target(root, item["meta"]["path"])
        if not target.exists(): missing += 1
        elif normalized(read_text(target)) == item["content"]: identical += 1
        else: different += 1
    print(f"Bundle: {path.name}")
    print(f"Files: {len(files)} | edited in bundle: {edited}")
    print(f"Compared with local source: {identical} identical, {different} different, {missing} missing")
    if errors:
        for error in errors: print(f"ERROR: {error}")
        return 1
    print("Bundle structure and paths are valid; safe to unpack.")
    return 0


def bundle_unpack(args: argparse.Namespace) -> int:
    root = bundle_root(args)
    path = root / (args.bundle or CODEBASE_FILE)
    files, errors = validate_bundle(path)
    if errors: raise ValueError("; ".join(errors))
    changed: list[tuple[Path, str]] = []
    for item in files:
        target = bundle_target(root, item["meta"]["path"])
        if not target.exists() or normalized(read_text(target)) != item["content"]:
            changed.append((target, item["content"]))
    backup: Path | None = None
    existing = [p for p, _ in changed if p.exists()]
    if existing and not args.no_backup:
        backup = root / BACKUP_FOLDER / now_stamp()
        for source in existing:
            destination = backup / source.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    for target, content in changed:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + f".{uuid.uuid4().hex}.tmp")
        temp.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temp, target)
    print(f"Restored {len(changed)} changed/missing SAS file(s).")
    if backup: print(f"Backup: {backup}")
    return 0


# ---------------------------------------------------------------------------
# EGP engine (ZIP/XML inspection and conservative extraction/repacking)
# ---------------------------------------------------------------------------


def choose_egp(value: str | None) -> Path:
    path = Path(value).expanduser() if value else find_one("*.egp", "EGP project")
    if not path.is_absolute(): path = (ROOT_DIR / path).resolve()
    if not path.is_file(): raise FileNotFoundError(path)
    return path


def egp_entries(path: Path) -> list[zipfile.ZipInfo]:
    with zipfile.ZipFile(path) as zf:
        return zf.infolist()


def embedded_sas_names(path: Path) -> list[str]:
    return sorted(i.filename for i in egp_entries(path) if i.filename.casefold().endswith(".sas"))


def egp_inspect(args: argparse.Namespace) -> int:
    path = choose_egp(args.project)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist(); sas = [n for n in names if n.casefold().endswith(".sas")]
        print(f"Project: {path}")
        print(f"Archive entries: {len(names)} | embedded SAS members: {len(sas)}")
        for name in sas: print(f"  {name}")
        xmls = [n for n in names if n.casefold().endswith(".xml")]
        for name in xmls[:5]:
            try:
                root = ET.fromstring(zf.read(name))
                labels = []
                for node in root.iter():
                    tag = node.tag.rsplit("}", 1)[-1].casefold()
                    if tag in {"label", "name"} and node.text and node.text.strip():
                        labels.append(node.text.strip())
                if labels: print(f"  {name}: " + ", ".join(dict.fromkeys(labels[:12])))
            except Exception: pass
    return 0


def egp_extract(args: argparse.Namespace) -> int:
    path = choose_egp(args.project)
    output = Path(args.output) if args.output else ROOT_DIR / path.stem
    if not output.is_absolute(): output = ROOT_DIR / output
    if output.exists(): raise FileExistsError(f"Output already exists; PySAS will not overwrite it: {output}")
    output.mkdir(parents=True)
    manifest: dict[str, str] = {}
    with zipfile.ZipFile(path) as zf:
        sas = [n for n in zf.namelist() if n.casefold().endswith(".sas")]
        used: set[str] = set()
        for index, member in enumerate(sas, 1):
            leaf = safe_name(Path(member).stem) + ".sas"
            if leaf.casefold() in used: leaf = f"{Path(leaf).stem}_{index:03d}.sas"
            used.add(leaf.casefold())
            (output / leaf).write_bytes(zf.read(member))
            manifest[leaf] = member
    (output / ".pysas_egp_manifest.json").write_text(json.dumps({
        "source": str(path), "members": manifest,
    }, indent=2), encoding="utf-8")
    print(f"Extracted {len(manifest)} SAS member(s): {output}")
    return 0


def egp_pack(args: argparse.Namespace) -> int:
    source = Path(args.source)
    if not source.is_absolute(): source = (ROOT_DIR / source).resolve()
    template = choose_egp(args.template)
    manifest_path = source / ".pysas_egp_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("The source folder has no .pysas_egp_manifest.json; extract it with PySAS first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))["members"]
    replacements = {member: (source / leaf).read_bytes() for leaf, member in manifest.items() if (source / leaf).is_file()}
    output = Path(args.output) if args.output else ROOT_DIR / f"{source.name}.egp"
    if not output.is_absolute(): output = ROOT_DIR / output
    if output.exists(): raise FileExistsError(f"Output already exists: {output}")
    with zipfile.ZipFile(template) as zin, zipfile.ZipFile(output, "w") as zout:
        for info in zin.infolist():
            zout.writestr(info, replacements.get(info.filename, zin.read(info.filename)))
    print(f"Repacked {len(replacements)} SAS member(s): {output}")
    return 0


# ---------------------------------------------------------------------------
# Enterprise Guide automation and runner
# ---------------------------------------------------------------------------


VBS = r'''Option Explicit
Dim mode, projectPath, sasPath, programName, rowStart, rowEnd, logPath, codePath
Dim resultDir, tableManifest, tempPrefix, app, project, code, fso, stream, text, exitCode, sourceCode, selection
exitCode = 0
mode = WScript.Arguments(0)
projectPath = WScript.Arguments(1)
sasPath = WScript.Arguments(2)
programName = WScript.Arguments(3)
rowStart = CLng(WScript.Arguments(4))
rowEnd = CLng(WScript.Arguments(5))
logPath = WScript.Arguments(6)
codePath = WScript.Arguments(7)
resultDir = WScript.Arguments(8)
tableManifest = WScript.Arguments(9)
tempPrefix = WScript.Arguments(10)
Set fso = CreateObject("Scripting.FileSystemObject")

Function ReadAll(path)
  Dim s
  Set s = CreateObject("ADODB.Stream")
  s.Type = 2
  s.Charset = "utf-8"
  s.Open
  s.LoadFromFile path
  ReadAll = s.ReadText
  s.Close
End Function

Function RangeText(firstLine, lastLine)
  Dim first, last
  first = ""
  last = ""
  If firstLine > 0 Then first = CStr(firstLine)
  If lastLine > 0 Then last = CStr(lastLine)
  RangeText = ""
  If first <> "" Or last <> "" Then RangeText = first & ":" & last
End Function

Function SelectionLabel(ByVal firstLine, ByVal lastLine, ByVal section)
  SelectionLabel = "whole program"
  If section <> "" Then
    SelectionLabel = "section " & section
  ElseIf firstLine > 0 Or lastLine > 0 Then
    If firstLine = 0 Then firstLine = 1
    If lastLine = 0 Then lastLine = "end"
    SelectionLabel = "rows " & firstLine & " to " & lastLine
  End If
End Function

Sub CleanExit(message, status)
  WScript.Echo message
  On Error Resume Next
  project.Close
  app.Quit
  On Error GoTo 0
  WScript.Quit status
End Sub

Function FindProgram(requestedName)
    Dim item, matchCount, matchedItem
    matchCount = 0
    For Each item In project.CodeCollection
        If LCase(Trim(item.Name)) = LCase(Trim(requestedName)) Then
            matchCount = matchCount + 1
            Set matchedItem = item
        End If
    Next
    If matchCount = 0 Then CleanExit "ERROR: Program not found: " & requestedName, 14
    If matchCount > 1 Then CleanExit "ERROR: Program name is duplicated: " & requestedName, 29
    Set FindProgram = matchedItem
End Function

Function GetSelectedText(requestedName, requestedRange, requestedSection)
    Dim item, textValue
    Set item = FindProgram(requestedName)
    textValue = item.Text
    If requestedSection <> "" And requestedRange <> "" Then CleanExit "ERROR: Specify either section or row range, not both.", 23
    If requestedSection <> "" Then
        textValue = ExtractSection(textValue, requestedSection)
        WScript.Echo "Always/target section selected: " & requestedSection
    ElseIf requestedRange <> "" Then
        textValue = ExtractRange(textValue, requestedRange)
        WScript.Echo "Always/target range selected: " & requestedRange
    End If
    GetSelectedText = textValue
End Function

Function ExtractSection(textValue, requestedSection)
    Dim normalized, lines, i, startIndex, endIndex, startCount, endCount
    Dim startMarker, endMarker, selected
    normalized = Replace(textValue, vbCrLf, vbLf)
    normalized = Replace(normalized, vbCr, vbLf)
    lines = Split(normalized, vbLf)
    startMarker = LCase("* (please do not delete) section_start: " & requestedSection & ";")
    endMarker = LCase("* (please do not delete) section_end: " & requestedSection & ";")
    startIndex = -1
    endIndex = -1
    startCount = 0
    endCount = 0
    For i = 0 To UBound(lines)
        If LCase(Trim(lines(i))) = startMarker Then
            startCount = startCount + 1
            startIndex = i
        End If
        If LCase(Trim(lines(i))) = endMarker Then
            endCount = endCount + 1
            endIndex = i
        End If
    Next
    If startCount <> 1 Then CleanExit "ERROR: Expected exactly one section_start marker for: " & requestedSection, 24
    If endCount <> 1 Then CleanExit "ERROR: Expected exactly one section_end marker for: " & requestedSection, 25
    If endIndex <= startIndex Then CleanExit "ERROR: Section end must appear after section start: " & requestedSection, 26
    selected = ""
    For i = startIndex + 1 To endIndex - 1
        selected = selected & lines(i)
        If i < endIndex - 1 Then selected = selected & vbCrLf
    Next
    ExtractSection = selected
End Function

Function ExtractRange(textValue, requestedRange)
    Dim parts, normalized, lines, startLine, endLine, totalLines, i, selected
    parts = Split(requestedRange, ":")
    If UBound(parts) <> 1 Then CleanExit "ERROR: Invalid range. Expected 20:45, 20:, or :45", 15
    normalized = Replace(textValue, vbCrLf, vbLf)
    normalized = Replace(normalized, vbCr, vbLf)
    lines = Split(normalized, vbLf)
    totalLines = UBound(lines) + 1
    If Trim(parts(0)) = "" Then
        startLine = 1
    ElseIf IsNumeric(Trim(parts(0))) Then
        startLine = CLng(Trim(parts(0)))
    Else
        CleanExit "ERROR: Start line must be numeric.", 16
    End If
    If Trim(parts(1)) = "" Then
        endLine = totalLines
    ElseIf IsNumeric(Trim(parts(1))) Then
        endLine = CLng(Trim(parts(1)))
    Else
        CleanExit "ERROR: End line must be numeric.", 16
    End If
    If startLine < 1 Or endLine < startLine Then CleanExit "ERROR: Invalid line range: " & requestedRange, 17
    If endLine > totalLines Then CleanExit "ERROR: End line exceeds program length. Program lines: " & totalLines, 18
    selected = ""
    For i = startLine To endLine
        selected = selected & lines(i - 1)
        If i < endLine Then selected = selected & vbCrLf
    Next
    ExtractRange = selected
End Function

Function CleanName(value)
  Dim chars, i, c, answer
  chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
  answer = ""
  For i = 1 To Len(value)
    c = Mid(value, i, 1)
    If InStr(chars, c) > 0 Then answer = answer & c Else answer = answer & "_"
  Next
  If Len(answer) = 0 Then answer = "item"
  CleanName = Left(answer, 60)
End Function

Sub SaveOutputs(theCode)
  Dim i, item, outPath, manifest, itemName
  On Error Resume Next
  Err.Clear
  theCode.Log.SaveAs logPath
  If Err.Number <> 0 Then
    WScript.Echo "ERROR: log save failed: " & Err.Description
    If exitCode = 0 Then exitCode = 21
  Else
    WScript.Echo "Log saved: " & logPath
  End If
  Err.Clear
  If UCase(mode) <> "RUNFILE" Then
    On Error GoTo 0
    Exit Sub
  End If
  For i = 0 To theCode.Results.Count - 1
    Set item = theCode.Results.Item(i)
    itemName = CleanName(item.Name)
    outPath = resultDir & "\" & itemName & "_" & Right("000" & CStr(i + 1), 3) & ".html"
    item.SaveAs outPath
    If Err.Number = 0 Then WScript.Echo "HTML result saved: " & outPath Else WScript.Echo "WARNING: result save failed: " & Err.Description
    Err.Clear
  Next
  If Len(tableManifest) > 0 Then
    Set manifest = fso.OpenTextFile(tableManifest, 2, True)
    For i = 0 To theCode.OutputDatasets.Count - 1
      Set item = theCode.OutputDatasets.Item(i)
      itemName = CleanName(item.Name)
      outPath = tempPrefix & "_" & Right("000" & CStr(i + 1), 3) & ".xlsx"
      item.SaveAs outPath
      If Err.Number = 0 Then manifest.WriteLine itemName & vbTab & outPath Else WScript.Echo "WARNING: table export failed: " & Err.Description
      Err.Clear
    Next
    manifest.Close
  End If
  On Error GoTo 0
End Sub

On Error Resume Next
WScript.Echo "PYSAS_STAGE|opening|Starting Enterprise Guide automation"
Set app = CreateObject("SASEGObjectModel.Application.8.1")
If Err.Number <> 0 Then
  Err.Clear
  Set app = CreateObject("SASEGObjectModel.Application.7.1")
End If
If Err.Number <> 0 Then
  WScript.Echo "ERROR: Could not start SAS Enterprise Guide automation: " & Err.Description
  WScript.Quit 20
End If
WScript.Echo "PYSAS_STAGE|opening|Opening Enterprise Guide project"
Err.Clear
Set project = app.Open(projectPath, "")
If Err.Number <> 0 Then CleanExit "ERROR: Could not open project: " & Err.Description, 13
On Error GoTo 0

If UCase(mode) = "RUNFILE" Then
  If project.CodeCollection.Count = 0 Then CleanExit "ERROR: Template EGP needs a code object with a SAS server connection.", 33
  For Each sourceCode In project.CodeCollection
    Exit For
  Next
  text = ReadAll(sasPath)
  selection = "whole file"
Else
  Dim setupDoc, setupNode, initText, piece, section, stopProgram
  If Not fso.FileExists(sasPath) Then CleanExit "ERROR: Shared setup manifest not found: " & sasPath, 27
  Set setupDoc = CreateObject("MSXML2.DOMDocument.6.0")
  setupDoc.async = False
  If Not setupDoc.Load(sasPath) Then CleanExit "ERROR: Cannot read shared setup definitions", 28
  section = setupDoc.documentElement.getAttribute("section")
  stopProgram = setupDoc.documentElement.getAttribute("stop_program")
  If IsNull(section) Then section = ""
  initText = ""
  For Each setupNode In setupDoc.selectNodes("/setup/program")
    WScript.Echo "PYSAS_STAGE|preparing|Appending shared setup: " & setupNode.getAttribute("name") & " (" & SelectionLabel(CLng(setupNode.getAttribute("first")), CLng(setupNode.getAttribute("last")), setupNode.getAttribute("section")) & ")"
    piece = GetSelectedText(setupNode.getAttribute("name"), RangeText(CLng(setupNode.getAttribute("first")), CLng(setupNode.getAttribute("last"))), setupNode.getAttribute("section"))
    If initText <> "" Then initText = initText & vbCrLf
    initText = initText & "/* ALWAYS_RUN_ITEM: " & setupNode.getAttribute("name") & " */" & vbCrLf & piece
  Next
  selection = SelectionLabel(rowStart, rowEnd, section)
  WScript.Echo "PYSAS_STAGE|preparing|Appending task program: " & programName & " (" & selection & ")"
  piece = GetSelectedText(programName, RangeText(rowStart, rowEnd), section)
  text = "options iomlogautoflush;" & vbCrLf
  If stopProgram = "1" Then text = "options iomlogautoflush errorabend errorcheck=strict;" & vbCrLf
  If initText <> "" Then text = text & "/* ALWAYS_RUN_INITIALIZATION_START */" & vbCrLf & initText & vbCrLf & "/* ALWAYS_RUN_INITIALIZATION_END */" & vbCrLf
  text = text & "/* SCHEDULED_TARGET_START */" & vbCrLf & piece & vbCrLf & "/* SCHEDULED_TARGET_END */"
  Set sourceCode = FindProgram(programName)
End If

Set code = project.CodeCollection.Add
code.Text = text
' Preserve the source program's server, as in the working Rich-terminal 0.3.2.
code.Server = sourceCode.Server
If UCase(mode) = "RUNFILE" Then
  On Error Resume Next
  code.UseApplicationOptions = True
  On Error GoTo 0
End If
Dim saved
Set saved = CreateObject("ADODB.Stream")
saved.Type = 2
saved.Charset = "utf-8"
saved.Open
saved.WriteText code.Text
saved.SaveToFile codePath, 2
saved.Close
WScript.Echo "PYSAS_STAGE|prepared|Submitted code saved: " & codePath
WScript.Echo "PYSAS_STAGE|executing|Running: " & programName & " (" & selection & ")"
On Error Resume Next
Err.Clear
code.Run
If Err.Number <> 0 Then
  WScript.Echo "ERROR: Enterprise Guide reported an execution failure: " & Err.Description
  exitCode = 20
End If
On Error GoTo 0
WScript.Echo "PYSAS_STAGE|exporting|SAS returned; saving logs and results"
SaveOutputs code
If UCase(mode) = "RUNFILE" Then WScript.Echo "EG Results detected: " & code.Results.Count
WScript.Echo "PYSAS_STAGE|closing|Closing project"
project.Close
WScript.Echo "PYSAS_STAGE|closing|Closing Enterprise Guide"
app.Quit
WScript.Echo "PYSAS_STAGE|complete|Automation completed"
WScript.Quit exitCode
'''


def cscript_path() -> Path:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    wow = windir / "SysWOW64" / "cscript.exe"
    return wow if wow.exists() else windir / "System32" / "cscript.exe"


def notify(title: str, message: str, error: bool = False, flash: bool = False) -> None:
    if os.name != "nt": return
    icon = "Error" if error else "Information"
    escaped_title = title.replace("'", "''"); escaped_message = message.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
        "$n=New-Object System.Windows.Forms.NotifyIcon; "
        f"$n.Icon=[System.Drawing.SystemIcons]::{icon}; $n.BalloonTipTitle='{escaped_title}'; "
        f"$n.BalloonTipText='{escaped_message}'; $n.Visible=$true; $n.ShowBalloonTip(5000); "
        "Start-Sleep -Seconds 6; $n.Dispose()"
    )
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if flash:
            subprocess.Popen(["powershell", "-NoProfile", "-Command",
                              "$w=New-Object -ComObject WScript.Shell; $w.AppActivate($PID) | Out-Null"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def compose_sas(source: Path, result_dir: Path, explicit_lib: Path | None = None,
                init_dir: Path | None = None, extra_init_dir: Path | None = None,
                parameters: Path | None = None, parameter_source: Path | None = None) -> str:
    parts = ["options iomlogautoflush;\n",
             f"%let PYSAS_RESULT_DIR=\"{result_dir.as_posix()}\";\n",
             "/* PYSAS_LIB_START */\n"]
    selected_parameters = (parameter_source or parameters).resolve() if parameters is not None else None
    for path in init_files(explicit_lib, init_dir, extra_init_dir):
        if selected_parameters is not None and path.resolve() == selected_parameters:
            continue  # A selected _*.sas parameter file belongs after initialization.
        parts += [f"/* PYSAS_INIT_FILE_START: {path.name} */\n", normalized(read_text(path)),
                  f"/* PYSAS_INIT_FILE_END: {path.name} */\n"]
    parts += ["/* PYSAS_LIB_END */\n"]
    if parameters is not None:
        parts += ["/* PYSAS_PARAMETERS_START */\n", normalized(read_text(parameters)), "/* PYSAS_PARAMETERS_END */\n"]
    parts += [f"/* PYSAS_JOB_START: {source.name} */\n",
              normalized(read_text(source)), f"/* PYSAS_JOB_END: {source.name} */\n"]
    return "".join(parts)


def combine_workbooks(manifest_path: Path, output: Path) -> int:
    Workbook, load_workbook, _, _, _ = require_openpyxl()
    if not manifest_path.exists(): return 0
    rows = []
    for line in manifest_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "\t" in line:
            name, path = line.split("\t", 1); rows.append((name, Path(path)))
    if not rows: return 0
    final = Workbook(); final.remove(final.active); used: set[str] = set(); copied = 0
    for raw_name, temp_path in rows:
        if not temp_path.exists(): continue
        source = load_workbook(temp_path, data_only=False, read_only=False)
        for source_ws in source.worksheets:
            base = safe_name(raw_name or source_ws.title, 31)[:31] or "table"
            title = base; suffix = 2
            while title.casefold() in used:
                tail = f"_{suffix}"; title = base[:31-len(tail)] + tail; suffix += 1
            used.add(title.casefold()); target = final.create_sheet(title)
            for row in source_ws.iter_rows():
                for cell in row:
                    dest = target.cell(cell.row, cell.column, cell.value)
                    dest.number_format = cell.number_format
            copied += 1
        source.close()
        try: temp_path.unlink()
        except OSError: pass
    if copied: final.save(output)
    return copied


def detect_sas_error(log_path: Path) -> bool:
    if not log_path.exists(): return False
    return bool(re.search(r"(?mi)^\s*ERROR(?:\s+\d+-\d+)?:", read_text(log_path)))


def report_progress(run_dir: Path, phase: str, message: str) -> None:
    """The CLI and UI observe the same execution milestones."""
    with PRINT_LOCK:
        print(f"[{run_dir.name}] {message}", flush=True)


def forward_bridge_progress(path: Path, offset: int, pending: bytes, run_dir: Path):
    try:
        with path.open("rb") as source:
            source.seek(offset)
            chunk = source.read()
            offset = source.tell()
    except OSError:
        return offset, pending  # Observation must not interrupt an executing SAS process.
    lines = (pending + chunk).split(b"\n")
    pending = lines.pop()
    for raw in lines:
        line = raw.decode(text_encoding(raw), errors="replace").strip()
        if line.startswith("PYSAS_STAGE|") and line.count("|") >= 2:
            _, phase, message = line.split("|", 2)
            report_progress(run_dir, phase, message)
    return offset, pending


def execute_eg(mode: str, project: Path, sas_path: Path, program: str, row_start: int,
               row_end: int, run_dir: Path, tables: bool, cancel_file: str | Path | None = None) -> tuple[int, str]:
    project, sas_path, run_dir = project.resolve(), sas_path.resolve(), run_dir.resolve()
    logs = run_dir / "logs"; code_dir = run_dir / "code"; results = run_dir / "results"
    for folder in (logs, code_dir, results): folder.mkdir(parents=True, exist_ok=True)
    def cancellation_requested():
        return (run_dir / "_cancel.request").exists() or bool(cancel_file and Path(cancel_file).exists())
    if cancellation_requested():
        message = "Stopped by user before Enterprise Guide was started.\n"
        (run_dir / "console.txt").write_text(message, encoding="utf-8")
        return 130, message
    stem = safe_name(Path(program or sas_path.name).stem)
    log_path = logs / f"{stem}.log"; code_path = code_dir / f"{stem}.sas"
    manifest = run_dir / "_table_manifest.tsv" if tables else Path("")
    temp_prefix = run_dir / "_pysas_table"
    fd, vbs_name = tempfile.mkstemp(prefix="pysas_", suffix=".vbs")
    os.close(fd); vbs_path = Path(vbs_name)
    vbs_path.write_text(VBS, encoding="utf-16")
    command = [str(cscript_path()), "//nologo", str(vbs_path), mode, str(project), str(sas_path),
               program, str(row_start), str(row_end), str(log_path), str(code_path), str(results),
               str(manifest) if tables else "", str(temp_prefix)]
    console_path = run_dir / "console.txt"
    rc = 127
    try:
        # A file cannot keep the parent waiting for EOF when EG leaves a child alive.
        with console_path.open("wb", buffering=0) as output:
            # Inherit the worker/terminal console and stdin, just as 0.3.2 did.
            process = subprocess.Popen(command, cwd=run_dir, stdout=output, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
            cancelled = False
            offset, pending_output = 0, b""
            while process.poll() is None:
                offset, pending_output = forward_bridge_progress(console_path, offset, pending_output, run_dir)
                if cancellation_requested():
                    # Target only the automation process owned by this file, never all SAS/EG processes.
                    try:
                        if os.name == "nt":
                            stopped = subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                                                     capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
                            if stopped.returncode and process.poll() is None:
                                raise OSError("Windows refused the stop request")
                        else:
                            process.kill()
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        output.write(f"Stop request not completed: {exc}. Retrying while the file remains active.\n".encode("utf-8"))
                        output.flush()
                        time.sleep(3)
                        continue
                    cancelled = True
                    break
                time.sleep(.2)
            rc = process.wait()
            forward_bridge_progress(console_path, offset, pending_output, run_dir)
            if cancelled:
                rc = 130
                output.write(b"Stopped by user. The local automation process was terminated; verify remote SAS session state if needed.\n")
    except OSError as exc:
        with console_path.open("a", encoding="utf-8") as output:
            output.write(f"ERROR: Enterprise Guide automation: {exc}\n")
    finally:
        try: vbs_path.unlink()
        except OSError: pass
    console = re.sub(r"(?m)^PYSAS_STAGE\|[^|]+\|", "", read_text(console_path))
    if tables:
        combine_workbooks(manifest, results / f"{stem}_tables.xlsx")
        try: manifest.unlink()
        except OSError: pass
    return rc, console


def run_job(source: Path, project: Path, tables: bool, explicit_lib: Path | None,
            notify_user: bool, runs_dir: Path | None = None, display_name: str | None = None,
            init_dir: Path | None = None, extra_init_dir: Path | None = None,
            parameters: Path | None = None) -> dict[str, Any]:
    if parameters is not None:
        parameters = Path(parameters).resolve()
        if parameters == source.resolve() or explicit_lib is not None and parameters == explicit_lib.resolve():
            raise ValueError("Choose a parameters file separate from the program and initialization override.")
        parameter_code = read_text(parameters)  # Read once; the archived copy is what will execute.
    logical_stem = re.sub(r"(?i)\.tables$", "", source.stem)
    base = safe_name(logical_stem)
    root = runs_dir or (ROOT_DIR / "runner" / "runs")
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / f"{now_stamp()}__{base}"
    suffix = 2
    while run_dir.exists(): run_dir = root / f"{now_stamp()}__{base}_{suffix}"; suffix += 1
    run_dir.mkdir(parents=True)
    source_dir = run_dir / "source"
    source_dir.mkdir()
    shutil.copy2(source, source_dir / source.name)
    parameter_copy = None
    if parameters is not None:
        parameter_folder = run_dir / "parameters"
        parameter_folder.mkdir()
        parameter_copy = parameter_folder / parameters.name
        parameter_copy.write_text(parameter_code, encoding="utf-8")
        print(f"Parameters: {parameters.name} (after shared initialization, before {source.name})", flush=True)
    submitted = run_dir / "_submitted.sas"
    submitted.write_text(compose_sas(source, run_dir / "results", explicit_lib, init_dir, extra_init_dir,
                                    parameters=parameter_copy, parameter_source=parameters), encoding="utf-8")
    started = time.time()
    rc, console = execute_eg("RUNFILE", project, submitted, display_name or source.name, 0, 0, run_dir, tables)
    log_files = list((run_dir / "logs").glob("*.log"))
    sas_error = any(detect_sas_error(p) for p in log_files)
    if rc == 130: status = "CANCELLED"
    elif rc != 0: status = "FAILED"
    elif sas_error: status = "SAS_ERROR"
    else: status = "SUCCESS"
    elapsed = time.time() - started
    (run_dir / "status.txt").write_text(
        f"status={status}\nsource={source.name}\nstarted={datetime.fromtimestamp(started).isoformat(timespec='seconds')}\n"
        f"finished={datetime.now().isoformat(timespec='seconds')}\nelapsed_seconds={elapsed:.1f}\n",
        encoding="utf-8")
    if status == "SUCCESS":
        try: submitted.unlink()
        except OSError: pass
    if notify_user:
        label = "completed" if status == "SUCCESS" else ("completed with SAS errors" if status == "SAS_ERROR" else "runner failed")
        notify("PySAS", f"{source.name}: {label}", error=status != "SUCCESS")
    return {"name": source.name, "status": status, "run_dir": run_dir, "elapsed": elapsed, "console": console}


def runner_run(args: argparse.Namespace) -> int:
    source = Path(args.program).expanduser()
    if not source.is_absolute(): source = (Path.cwd() / source).resolve()
    if not source.is_file(): raise FileNotFoundError(source)
    project = choose_egp(args.template)
    tables = bool(args.tables or re.search(r"(?i)\.tables\.sas$", source.name))
    lib = Path(args.lib).resolve() if args.lib else None
    init_dir = Path(args.init_dir).expanduser().resolve() if getattr(args, "init_dir", None) else None
    if init_dir is not None and not init_dir.is_dir(): raise FileNotFoundError(init_dir)
    parameters = Path(args.parameters).expanduser().resolve() if getattr(args, "parameters", None) else None
    result = run_job(source, project, tables, lib, not args.no_notify, init_dir=init_dir, parameters=parameters)
    label = {"SUCCESS": "DONE", "SAS_ERROR": "DONE WITH SAS ERRORS", "FAILED": "RUNNER FAILED"}[result["status"]]
    print(f"{label}: {source.name}")
    print(result["run_dir"])
    return 0 if result["status"] == "SUCCESS" else 1


def format_elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds)); hours, rem = divmod(seconds, 3600); minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def dashboard(running: dict[str, float], inbox: Path, runs: Path, max_ready: int = 3) -> str:
    lines = [f"PySAS {VERSION} watcher", "─" * 48, "", "Running now"]
    if running:
        for name, began in sorted(running.items(), key=lambda x: x[1]):
            lines.append(f"  ● {name:<30} {format_elapsed(time.time() - began)}")
    else: lines.append("  — idle —")
    ready = sorted((p for p in runs.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True) if runs.exists() else []
    lines += ["", f"Ready to review ({len(ready)})"]
    for path in ready[:max_ready]: lines.append(f"  ✓ {path.name}")
    if len(ready) > max_ready: lines.append(f"  … and {len(ready) - max_ready} more in runner\\runs")
    queued = sum(1 for p in sas_files(inbox) if not p.name.startswith("_")) if inbox.exists() else 0
    if queued: lines += ["", f"Queued in inbox: {queued}"]
    lines += ["", f"Drop job .sas files into {inbox}. _*.sas files are shared initialization. Press Ctrl+C to stop."]
    return "\n".join(lines)


def runner_watch(args: argparse.Namespace) -> int:
    root = ROOT_DIR / "runner"
    inbox = Path(args.inbox).expanduser().resolve() if getattr(args, "inbox", None) else root / "inbox"
    # Claim on the inbox volume so custom/network inboxes can be moved atomically.
    claimed = root / "claimed" if inbox.resolve() == (root / "inbox").resolve() else inbox / ".pysas-claimed"
    runs = root / "runs"
    init_dir = Path(args.init_dir).expanduser().resolve() if getattr(args, "init_dir", None) else None
    if init_dir is not None and not init_dir.is_dir(): raise FileNotFoundError(init_dir)
    for path in (inbox, claimed, runs): path.mkdir(parents=True, exist_ok=True)
    project = choose_egp(args.template); lib = Path(args.lib).resolve() if args.lib else None
    max_workers = max(1, args.workers); running: dict[str, float] = {}; futures: dict[Any, tuple[str, Path]] = {}
    seen_stable: dict[Path, tuple[int, float]] = {}
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    ansi = sys.stdout.isatty()
    try:
        while True:
            for path in sorted(sas_files(inbox)):
                if path.name.startswith("_"): continue
                try: state = (path.stat().st_size, path.stat().st_mtime)
                except FileNotFoundError: continue
                if seen_stable.get(path) != state:
                    seen_stable[path] = state; continue
                if len(futures) >= max_workers: break
                claim_dir = claimed / uuid.uuid4().hex[:8]; claim_dir.mkdir()
                claimed_file = claim_dir / path.name
                try: path.replace(claimed_file)
                except (FileNotFoundError, PermissionError): continue
                seen_stable.pop(path, None)
                tables = bool(args.tables or re.search(r"(?i)\.tables\.sas$", claimed_file.name))
                future = executor.submit(run_job, claimed_file, project, tables, lib, not args.no_notify, runs, path.name, init_dir, inbox)
                futures[future] = (path.name, claim_dir); running[path.name] = time.time()
            for future in list(futures):
                if not future.done(): continue
                name, claim_dir = futures.pop(future); running.pop(name, None)
                try:
                    result = future.result(); print(f"\n{result['status']}: {name} -> {result['run_dir'].name}")
                except Exception as exc:
                    print(f"\nRUNNER FAILED: {name}: {exc}")
                    if not args.no_notify: notify("PySAS", f"{name}: runner failed", error=True)
                shutil.rmtree(claim_dir, ignore_errors=True)
            if ansi: print("\x1b[2J\x1b[H", end="")
            print(dashboard(running, inbox, runs), flush=True)
            time.sleep(max(0.5, args.poll))
    except KeyboardInterrupt:
        print("\nWatcher stopped. Running jobs will be allowed to finish.")
        return 130
    finally:
        executor.shutdown(wait=True, cancel_futures=False)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


def clean_int(value: Any, field: str, row: int) -> int | None:
    if value is None or str(value).strip() == "": return None
    number = float(value)
    if not number.is_integer(): raise ValueError(f"Excel row {row}: {field} must be an integer")
    return int(number)


def find_scheduler(value: str | None) -> Path:
    if value:
        path = Path(value); path = path if path.is_absolute() else ROOT_DIR / path
        return path.resolve()
    choices = sorted(p for p in ROOT_DIR.glob("*.xlsx") if not p.name.startswith("~$") and
                     p.name.casefold() != "run_summary.xlsx" and not p.stem.casefold().endswith("__next"))
    if len(choices) != 1: raise RuntimeError("Expected exactly one scheduler workbook; use --workbook")
    return choices[0]


def load_schedule(path: Path) -> list[dict[str, Any]]:
    _, load_workbook, _, _, _ = require_openpyxl()
    # Own the input handle: openpyxl row iterators can outlive early validation.
    with path.open("rb") as source:
        wb = load_workbook(source, data_only=True, read_only=True)
        try:
            ws = wb["Schedule"] if "Schedule" in wb.sheetnames else wb[wb.sheetnames[0]]
            rows = ws.iter_rows(values_only=True)
            headers = [str(v or "").strip().casefold() for v in next(rows, [])]
            named_headers = [h for h in headers if h]
            if len(set(named_headers)) != len(named_headers): raise ValueError("Scheduler contains duplicate column headers")
            missing = REQUIRED_COLUMNS.difference(headers)
            if missing: raise ValueError("Missing scheduler columns: " + ", ".join(sorted(missing)))
            col = {name: headers.index(name) for name in REQUIRED_COLUMNS}; tasks = []; ids: set[str] = set()
            for excel_row, values in enumerate(rows, 2):
                if not any(v is not None and str(v).strip() for v in values): continue
                def value(name: str): return values[col[name]] if col[name] < len(values) else None
                task_id = str(value("task_id") or "").strip()
                if not task_id: raise ValueError(f"Excel row {excel_row}: task_id is required")
                if task_id.casefold() in ids: raise ValueError(f"Excel row {excel_row}: duplicate task_id: {task_id}")
                ids.add(task_id.casefold())
                dependencies = [x.strip() for x in str(value("depends_on") or "").split(",") if x.strip()]
                tasks.append({
                    "task_id": task_id, "program": str(value("program") or "").strip(), "depends_on": dependencies,
                    "skip": truthy(value("skip")), "row_start": clean_int(value("row_start"), "row_start", excel_row),
                    "row_end": clean_int(value("row_end"), "row_end", excel_row), "section": str(value("section") or "").strip(),
                    "stop_process_on_error": truthy(value("stop_process_on_error")),
                    "stop_program_on_error": truthy(value("stop_program_on_error")),
                    "max_parallel": clean_int(value("max_parallel"), "max_parallel", excel_row),
                    "always_run": truthy(value("always_run")), "excel_row": excel_row,
                })
            if not tasks: raise ValueError("Scheduler contains no tasks")
            known = {t["task_id"].casefold() for t in tasks}
            for task in tasks:
                if not task["program"]: raise ValueError(f"{task['task_id']}: program is required")
                for field in ("row_start", "row_end"):
                    if task[field] == 0: task[field] = None
                    if task[field] is not None and task[field] < 1:
                        raise ValueError(f"{task['task_id']}: {field} must be blank, 0, or >= 1")
                if task["section"] and (task["row_start"] or task["row_end"]):
                    raise ValueError(f"{task['task_id']}: specify either section or row range, not both")
                if task["max_parallel"] is not None and task["max_parallel"] < 1:
                    raise ValueError(f"{task['task_id']}: max_parallel must be blank or at least 1")
                dependencies = [d.casefold() for d in task["depends_on"]]
                if len(dependencies) != len(set(dependencies)):
                    raise ValueError(f"{task['task_id']}: depends_on contains duplicates")
                absent = [d for d in task["depends_on"] if d.casefold() not in known]
                if absent: raise ValueError(f"{task['task_id']}: unknown dependencies: {', '.join(absent)}")
                if task["row_start"] and task["row_end"] and task["row_start"] > task["row_end"]:
                    raise ValueError(f"{task['task_id']}: row_start must not exceed row_end")
            dependencies = {t["task_id"].casefold(): {d.casefold() for d in t["depends_on"]} for t in tasks}
            waiting = set(dependencies)
            while waiting:
                ready = {key for key in waiting if not dependencies[key] & waiting}
                if not ready: raise ValueError("Circular dependency detected: " + ", ".join(sorted(waiting)))
                waiting -= ready
            return tasks
        finally:
            wb.close()


def describe_selection(task: dict[str, Any]) -> str:
    if task.get("section"):
        return f"section {task['section']}"
    if task.get("row_start") or task.get("row_end"):
        return f"rows {task.get('row_start') or 1} to {task.get('row_end') or 'end'}"
    return "whole program"


def scheduler_task(task: dict[str, Any], project: Path, task_root: Path) -> dict[str, Any]:
    task_dir = task_root / safe_name(task["task_id"]); task_dir.mkdir(parents=True, exist_ok=True)
    report_progress(task_dir, "preparing", f"Preparing {task['program']} ({describe_selection(task)})")
    task_project = task_dir / project.name; shutil.copy2(project, task_project)
    stop_program = task.get("stop_program_on_error", False) or any(t.get("stop_program_on_error") for t in task.get("_always_run", []))
    setup = ET.Element("setup", section=task.get("section", ""), stop_program="1" if stop_program else "0")
    for definition in task.get("_always_run", []):
        ET.SubElement(setup, "program", name=definition["program"],
                      first=str(definition["row_start"] or 0), last=str(definition["row_end"] or 0),
                      section=definition.get("section", ""))
    setup_path = task_dir / "shared_setup.xml"
    ET.ElementTree(setup).write(setup_path, encoding="utf-8", xml_declaration=True)
    report_progress(task_dir, "preparing", f"Shared setup: {len(task.get('_always_run', []))} definition(s) will be prepended")
    began = time.time()
    rc, console = execute_eg("RUNPROJECT", task_project, setup_path, task["program"],
                             task["row_start"] or 0, task["row_end"] or 0, task_dir, False,
                             cancel_file=task.get("_cancel_file"))
    logs = list((task_dir / "logs").glob("*.log")); sas_error = any(detect_sas_error(p) for p in logs)
    status = "CANCELLED" if rc == 130 else ("SAS_ERROR" if sas_error else ("FAILED" if rc else "SUCCESS"))
    evidence = console + "\n" + "\n".join(read_text(p) for p in logs)
    if any(pattern in evidence.casefold() for pattern in CONNECTION_PATTERNS): status = "CONNECTION_LOST"
    return {**task, "status": status, "elapsed": time.time() - began, "task_dir": task_dir,
            "message": console.strip().splitlines()[-1] if console.strip() else ""}


def report_task_result(result: dict[str, Any]) -> None:
    """Publish completion of a task that did not need an EG session."""
    with PRINT_LOCK:
        print(f"{result['task_id']}: {result['status']} · {result['message']}", flush=True)


def append_schedule_log_file(output, path: Path, console: bool = False) -> None:
    """Copy full text with bounded memory, including legacy Windows SAS encodings."""
    with path.open("rb") as source:
        encoding = text_encoding(source.read(4096))
    if encoding == "utf-8-sig":
        # An ASCII prefix does not distinguish UTF-8 from later cp1252 accents.
        try:
            with path.open(encoding=encoding) as source:
                while source.read(128 * 1024):
                    pass
        except UnicodeDecodeError:
            encoding = "cp1252"
    last = ""
    with path.open(encoding=encoding, errors="replace") as source:
        line_start = True
        while line := source.readline(128 * 1024):
            if console and line_start and line.startswith("PYSAS_STAGE|") and line.count("|") >= 2:
                line = line.split("|", 2)[2]
            output.write(line)
            line_start = line.endswith("\n")
            last = line
    if last and not last.endswith("\n"):
        output.write("\n")


def write_schedule_log(run_dir: Path, results: list[dict[str, Any]]) -> Path:
    """Combine task evidence in workbook order after a completed or stopped run."""
    target = run_dir / "schedule.log"
    fd, temporary_name = tempfile.mkstemp(prefix=".schedule-log-", suffix=".tmp", dir=run_dir)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write(f"PySAS {VERSION} — Full schedule log\nSchedule: {run_dir.name}\n")
            output.write("Tasks are grouped in workbook order; parallel task durations overlap.\n")
            output.write("Includes available SAS logs and automation console output.\n\n")
            for result in results:
                output.write(f"{result['task_id']}: {result['status']} — {result['program']} ({result.get('elapsed', 0):.1f}s)\n")
            for index, result in enumerate(results, 1):
                output.write("\n" + "=" * 80 + "\n")
                output.write(f"TASK {index}/{len(results)}: {result['task_id']} — {result['program']}\n")
                output.write(f"Selection: {describe_selection(result)}\nStatus: {result['status']}\nElapsed: {result.get('elapsed', 0):.1f} seconds\n")
                if result.get("message"):
                    output.write(f"Message: {result['message']}\n")
                folder = Path(result["task_dir"]) if result.get("task_dir") else None
                logs = sorted((folder / "logs").glob("*.log")) if folder else []
                if not logs:
                    note = "Shared setup is included in each target's SAS log." if result["status"] == "ALWAYS_RUN_DEFINITION" else "No SAS log was produced for this task."
                    output.write(note + "\n")
                evidence = [(path, False) for path in logs]
                if folder and (folder / "console.txt").is_file():
                    evidence.append((folder / "console.txt", True))
                for path, console in evidence:
                    output.write(f"\n--- {'Automation console' if console else 'SAS log'}: {path.name} ---\n")
                    try:
                        append_schedule_log_file(output, path, console=console)
                    except (OSError, ValueError) as exc:
                        output.write(f"\n[Could not read {path.name}: {exc}]\n")
            output.write("\n" + "=" * 80 + "\nEnd of full schedule log.\n")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def write_summary(run_dir: Path, results: list[dict[str, Any]]) -> None:
    fields = ["task_id", "program", "status", "elapsed", "depends_on", "message"]
    with (run_dir / "run_summary.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
        for r in results: writer.writerow({k:",".join(r[k]) if k == "depends_on" else r.get(k, "") for k in fields})
    text = [f"PySAS {VERSION} schedule summary", ""]
    text += [f"{r['task_id']}: {r['status']} ({r.get('elapsed', 0):.1f}s)" for r in results]
    (run_dir / "run_summary.txt").write_text("\n".join(text) + "\n", encoding="utf-8")
    write_schedule_log(run_dir, results)
    Workbook, _, Font, PatternFill, get_column_letter = require_openpyxl()
    wb = Workbook(); ws = wb.active; ws.title = "Summary"; ws.append(fields)
    for cell in ws[1]: cell.font = Font(bold=True); cell.fill = PatternFill("solid", fgColor="D9EAF7")
    for r in results: ws.append([",".join(r[k]) if k == "depends_on" else r.get(k, "") for k in fields])
    for index, name in enumerate(fields, 1): ws.column_dimensions[get_column_letter(index)].width = max(12, len(name) + 2)
    wb.save(run_dir / "run_summary.xlsx")


def schedule_run(args: argparse.Namespace) -> int:
    workbook = find_scheduler(args.workbook); project = choose_egp(args.project); tasks = load_schedule(workbook)
    base_runs = ROOT_DIR / "runs"; base_runs.mkdir(exist_ok=True); run_dir = base_runs / f"{now_stamp()}__schedule"
    suffix = 2
    while run_dir.exists(): run_dir = base_runs / f"{now_stamp()}__schedule_{suffix}"; suffix += 1
    run_dir.mkdir(); shutil.copy2(workbook, run_dir / workbook.name); shutil.copy2(project, run_dir / project.name)
    began = time.time()
    cancel_file = Path(args.cancel_file).resolve() if getattr(args, "cancel_file", None) else run_dir / "_cancel.request"
    definitions = [t for t in tasks if t["always_run"] and not t["skip"]]
    pending = {t["task_id"].casefold(): {**t, "_always_run": definitions, "_cancel_file": str(cancel_file)} for t in tasks if not t["always_run"]}
    results = [{**t, "status": "SKIPPED_SUCCESS" if t["skip"] else "ALWAYS_RUN_DEFINITION",
                "elapsed": 0.0, "message": "Marked skip" if t["skip"] else "Prepended before each program in workbook order"}
               for t in tasks if t["always_run"]]
    satisfied = {t["task_id"].casefold() for t in tasks if t["always_run"]}
    failed: set[str] = set(); stop = False; cancelled = False
    max_workers = args.workers if args.workers is not None else max((t["max_parallel"] for t in tasks if t["max_parallel"] is not None), default=10)
    if max_workers < 1: raise ValueError("Parallel runs must be at least 1")
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers); active: dict[Any, dict[str, Any]] = {}
    submitted_at: dict[str, float] = {}
    def resolve_pending(key, task, status, message):
        result = {**task, "status": status, "elapsed": 0.0, "message": message}
        results.append(result)
        (satisfied if status in FINAL_OK else failed).add(key)
        pending.pop(key)
        report_task_result(result)
    try:
        while pending or active:
            cancelled = cancelled or cancel_file.exists()
            pending_before = len(pending)
            for key, task in list(pending.items()):
                # Check the run-wide request before every launch, including skipped rows.
                cancelled = cancelled or cancel_file.exists()
                if cancelled:
                    resolve_pending(key, task, "CANCELLED", "Schedule stopped before this task started")
                    continue
                deps = {d.casefold() for d in task["depends_on"]}
                if stop:
                    resolve_pending(key, task, "STOPPED_ON_ERROR", "Not started after stop-on-error")
                    continue
                if deps & failed:
                    resolve_pending(key, task, "BLOCKED_DEPENDENCY", "Dependency failed")
                    continue
                # A skipped program is a dependency barrier, not an already completed job.
                # Resolving each barrier after its parents preserves arbitrary skipped chains.
                if not deps.issubset(satisfied): continue
                if task["skip"]:
                    resolve_pending(key, task, "SKIPPED_SUCCESS", "Skipped after dependencies completed")
                    continue
                if len(active) >= max_workers: continue
                submitted_at[key] = time.time()
                print(f"Launching {task['task_id']}: {task['program']} ({describe_selection(task)})", flush=True)
                future = executor.submit(scheduler_task, task, project, run_dir / "tasks")
                active[future] = task; pending.pop(key)
            if not active:
                if pending and len(pending) < pending_before:
                    continue
                if pending:
                    for key, task in list(pending.items()):
                        results.append({**task, "status": "BLOCKED_DEPENDENCY", "elapsed": 0.0,
                                        "message": "Circular/unresolved dependency"}); failed.add(key); pending.pop(key)
                break
            done, _ = concurrent.futures.wait(active, timeout=0.5, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                task = active.pop(future); key = task["task_id"].casefold()
                try:
                    result = future.result()
                except Exception as exc:
                    result = {**task, "status": "FAILED", "elapsed": time.time() - submitted_at[key],
                              "message": str(exc), "task_dir": run_dir / "tasks" / safe_name(task["task_id"])}
                results.append(result)
                if result["status"] == "SUCCESS": satisfied.add(key)
                else:
                    failed.add(key)
                    if result["status"] == "CONNECTION_LOST" or task["stop_process_on_error"] or any(t.get("stop_process_on_error") for t in definitions): stop = True
                print(f"{task['task_id']}: {result['status']}")
    finally: executor.shutdown(wait=True)
    order = {t["task_id"].casefold(): i for i, t in enumerate(tasks)}; results.sort(key=lambda r: order[r["task_id"].casefold()])
    cancelled = cancelled or cancel_file.exists()
    if cancelled:
        (run_dir / "status.txt").write_text(
            f"status=STOPPED\nstarted={datetime.fromtimestamp(began).isoformat()}\nelapsed_seconds={time.time() - began:.1f}\n", encoding="utf-8")
    write_summary(run_dir, results)
    errors = [r for r in results if r["status"] not in FINAL_OK]
    if not args.no_notify: notify("PySAS schedule", "Stopped by user" if cancelled else ("Completed successfully" if not errors else f"Completed with {len(errors)} error(s)"),
                                  error=bool(errors) and not cancelled, flash=bool(errors) and not cancelled)
    print(f"Schedule {'stopped' if cancelled else 'complete'}: {run_dir}")
    return 130 if cancelled else (1 if errors else 0)


def schedule_continue(args: argparse.Namespace) -> int:
    previous = Path(args.run_dir); previous = previous if previous.is_absolute() else ROOT_DIR / previous
    summaries = previous / "run_summary.csv"
    if not summaries.is_file(): raise FileNotFoundError(summaries)
    with summaries.open(encoding="utf-8-sig", newline="") as f:
        prior = {r["task_id"].casefold(): r["status"] for r in csv.DictReader(f)}
    workbook = next((p for p in previous.glob("*.xlsx") if p.name != "run_summary.xlsx"), None)
    project = next(iter(previous.glob("*.egp")), None)
    if not workbook or not project: raise FileNotFoundError("Continuation folder must contain its scheduler workbook and EGP")
    tasks = load_schedule(workbook)
    # Produce a temporary continuation workbook by marking successful rows as skipped.
    _, load_workbook, _, _, _ = require_openpyxl(); wb = load_workbook(workbook)
    ws = wb["Schedule"] if "Schedule" in wb.sheetnames else wb[wb.sheetnames[0]]
    headers = [str(c.value or "").strip().casefold() for c in ws[1]]; skip_col = headers.index("skip") + 1
    for task in tasks:
        if not task["always_run"] and prior.get(task["task_id"].casefold()) in FINAL_OK: ws.cell(task["excel_row"], skip_col).value = 1
    temp = ROOT_DIR / f"{workbook.stem}__next.xlsx"; wb.save(temp); wb.close()
    forwarded = argparse.Namespace(workbook=str(temp), project=str(project), workers=args.workers, no_notify=args.no_notify,
                                   cancel_file=getattr(args, "cancel_file", None))
    try: return schedule_run(forwarded)
    finally:
        try: temp.unlink()
        except OSError: pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pysas.py", description="PySAS — SAS Enterprise Guide command-line utilities")
    p.add_argument("--version", action="version", version=f"PySAS {VERSION}")
    subs = p.add_subparsers(dest="command")
    version = subs.add_parser("version", help="show version and exact script path")
    version.set_defaults(func=lambda a: (print(f"PySAS {VERSION}\nScript: {Path(__file__).resolve()}"), 0)[1])

    bundle = subs.add_parser("bundle", help="pack, verify or unpack SAS code bundles")
    bsub = bundle.add_subparsers(dest="bundle_command", required=True)
    bp = bsub.add_parser("pack"); bp.add_argument("--recursive", action="store_true"); bp.add_argument("--output"); bp.set_defaults(func=bundle_pack)
    bv = bsub.add_parser("verify"); bv.add_argument("--bundle"); bv.set_defaults(func=bundle_verify)
    bu = bsub.add_parser("unpack"); bu.add_argument("--bundle"); bu.add_argument("--no-backup", action="store_true"); bu.set_defaults(func=bundle_unpack)

    for command in (bp, bv, bu):
        command.add_argument("--root", help="code folder to pack, compare or restore (default: folder beside pysas.py)")

    egp = subs.add_parser("egp", help="inspect, extract or repack EGP projects")
    esub = egp.add_subparsers(dest="egp_command", required=True)
    ei = esub.add_parser("inspect"); ei.add_argument("project", nargs="?"); ei.set_defaults(func=egp_inspect)
    ee = esub.add_parser("extract"); ee.add_argument("project", nargs="?"); ee.add_argument("--output"); ee.set_defaults(func=egp_extract)
    ep = esub.add_parser("pack"); ep.add_argument("source"); ep.add_argument("--template"); ep.add_argument("--output"); ep.set_defaults(func=egp_pack)

    runner = subs.add_parser("runner", help="run or watch standalone SAS jobs; _*.sas init files run first")
    rsub = runner.add_subparsers(dest="runner_command", required=True)
    rr = rsub.add_parser("run"); rr.add_argument("program"); rr.add_argument("--template"); rr.add_argument("--lib")
    rr.add_argument("--parameters", help="SAS parameters to prepend after initialization and before the program"); rr.add_argument("--tables", action="store_true"); rr.add_argument("--no-notify", action="store_true"); rr.set_defaults(func=runner_run)
    rw = rsub.add_parser("watch"); rw.add_argument("--template"); rw.add_argument("--lib"); rw.add_argument("--tables", action="store_true")
    rw.add_argument("--workers", type=int, default=2); rw.add_argument("--poll", type=float, default=2.0)
    rw.add_argument("--no-notify", action="store_true"); rw.set_defaults(func=runner_watch)

    rr.add_argument("--init-dir", help="folder containing shared _*.sas initialization files")
    rw.add_argument("--init-dir", help="folder containing shared _*.sas initialization files")
    rw.add_argument("--inbox", help="folder to watch; _*.sas files here initialize jobs instead of being queued")

    schedule = subs.add_parser("schedule", help="run an Excel dependency schedule")
    schedule.add_argument("action", nargs="?", choices=["run", "continue"], default="run")
    schedule.add_argument("run_dir", nargs="?"); schedule.add_argument("--workbook"); schedule.add_argument("--project")
    schedule.add_argument("--workers", "--max-parallel", type=int, default=None, help="Maximum parallel runs (workbook max_parallel, otherwise 10)"); schedule.add_argument("--no-notify", action="store_true")
    schedule.add_argument("--cancel-file", help=argparse.SUPPRESS)
    schedule.set_defaults(func=lambda a: schedule_continue(a) if a.action == "continue" else schedule_run(a))
    return p


def main(argv: list[str] | None = None) -> int:
    if argv is None: argv = sys.argv[1:]
    if not argv:
        print_home(); return 0
    args = parser().parse_args(argv)
    if not hasattr(args, "func"):
        parser().print_help(); return 2
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr); return 130
    except Exception as exc:
        print(f"PySAS error: {exc}", file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
