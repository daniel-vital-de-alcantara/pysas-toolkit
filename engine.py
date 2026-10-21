"""Run one SAS file through Enterprise Guide; independent of PySAS and its UI.

Python 3.10+, Windows, and an installed/configured SAS Enterprise Guide are
required for execution. Only the standard library is used. See docs/engine.md.
"""
from __future__ import annotations

import codecs
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import traceback
from xml.etree import ElementTree as ET
import zipfile

__all__ = ["run_sas", "RunResult"]


@dataclass(frozen=True)
class RunResult:
    status: str
    output_dir: Path
    log: str = field(repr=False)
    log_path: Path
    html_files: tuple[Path, ...]
    table_files: tuple[Path, ...]
    submitted_path: Path
    console_path: Path
    elapsed_seconds: float
    returncode: int | None
    server: str | None
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def success(self) -> bool:
        return self.status == "SUCCESS"


# This bridge uses the same Open / CodeCollection.Add / Text / Server / Run /
# Log.SaveAs / Results / OutputDatasets operations as the working PySAS bridge.
# It has no scheduler, initialization discovery or dependency on pysas.py.
_VBS = r'''Option Explicit
Dim projectPath, sasPath, outDir, logPath, reportPath, wantHtml, wantTables, tableFormat, seedName
Dim app, project, code, sourceCode, candidate, servers, serverName, matches, text, n, item, path, label
Dim fso, report, root, version, count, node
projectPath = WScript.Arguments(0)
sasPath = WScript.Arguments(1)
outDir = WScript.Arguments(2)
wantHtml = (WScript.Arguments(3) = "1")
wantTables = (WScript.Arguments(4) = "1")
tableFormat = WScript.Arguments(5)
seedName = WScript.Arguments(6)
logPath = outDir & "\sas.log"
reportPath = outDir & "\_automation.xml"
Set fso = CreateObject("Scripting.FileSystemObject")
Set report = CreateObject("MSXML2.DOMDocument.6.0")
report.appendChild report.createProcessingInstruction("xml", "version='1.0' encoding='utf-8'")
Set root = report.createElement("run")
report.appendChild root
root.setAttribute "complete", "0"
root.setAttribute "ran", "0"

Sub Stage(phase)
  root.setAttribute "phase", phase
  report.save reportPath
  WScript.Echo "PYSAS_ENGINE|" & phase
End Sub

Sub Problem(kind, phase, message)
  Dim record
  Set record = report.createElement(kind)
  record.setAttribute "phase", phase
  record.text = message
  root.appendChild record
  Err.Clear
End Sub

Sub Finish(status)
  On Error Resume Next
  Err.Clear
  If IsObject(project) Then project.Close
  If Err.Number <> 0 Then Problem "error", "closing", "Project close: " & Err.Description
  Err.Clear
  If IsObject(app) Then app.Quit
  If Err.Number <> 0 Then Problem "error", "closing", "Enterprise Guide quit: " & Err.Description
  Err.Clear
  root.setAttribute "complete", "1"
  report.save reportPath
  If Err.Number <> 0 Then WScript.Echo "Manifest save failed: " & Err.Description
  If root.selectNodes("error").length > 0 Then status = 1
  WScript.Quit status
End Sub

Sub Fail(phase, message)
  Problem "error", phase, message
  Finish 1
End Sub

Function ReadAll(file)
  Dim stream
  Set stream = CreateObject("ADODB.Stream")
  stream.Type = 2
  stream.Charset = "utf-8"
  stream.Open
  stream.LoadFromFile file
  ReadAll = stream.ReadText
  stream.Close
End Function

Function CleanName(value)
  Dim i, character, answer
  answer = ""
  For i = 1 To Len(value)
    character = Mid(value, i, 1)
    If InStr("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-", character) > 0 Then
      answer = answer & character
    Else
      answer = answer & "_"
    End If
  Next
  If Len(answer) = 0 Then answer = "output"
  CleanName = Left(answer, 60)
End Function

Sub ExportItem(value, kind, relativePath)
  Dim record, description
  On Error Resume Next
  Err.Clear
  value.SaveAs outDir & "\" & relativePath
  If Err.Number <> 0 Then
    description = Err.Description
    Problem "export-error", kind, relativePath & ": " & description
  ElseIf Not fso.FileExists(outDir & "\" & relativePath) Then
    Problem "export-error", kind, relativePath & ": SaveAs returned without a file"
  Else
    Set record = report.createElement("output")
    record.setAttribute "kind", kind
    record.setAttribute "path", Replace(relativePath, "\", "/")
    root.appendChild record
  End If
  Err.Clear
  report.save reportPath
End Sub

On Error Resume Next
Stage "opening"
For Each version In Array("8.1", "7.1")
  Err.Clear
  Set app = CreateObject("SASEGObjectModel.Application." & version)
  If Err.Number = 0 Then Exit For
Next
If Err.Number <> 0 Then Fail "opening", "Cannot start SAS Enterprise Guide automation: " & Err.Description
Err.Clear
Set project = app.Open(projectPath, "")
If Err.Number <> 0 Then Fail "opening", "Cannot open EGP: " & Err.Description

Stage "selecting server"
Set servers = CreateObject("Scripting.Dictionary")
servers.CompareMode = 1
Set sourceCode = Nothing
matches = 0
Err.Clear
For Each candidate In project.CodeCollection
  If seedName = "" Or LCase(Trim(candidate.Name)) = LCase(Trim(seedName)) Then
    serverName = candidate.Server
    If Len(Trim(serverName)) > 0 Then
      matches = matches + 1
      If Not servers.Exists(serverName) Then servers.Add serverName, True
      If sourceCode Is Nothing Then Set sourceCode = candidate
    End If
  End If
Next
If Err.Number <> 0 Then Fail "selecting server", "Cannot read the EGP code connections: " & Err.Description
If matches = 0 Then Fail "selecting server", "No connected code node found. Check server_program and the EGP's SAS connection."
If seedName <> "" And matches > 1 Then Fail "selecting server", "server_program matches more than one EGP node. Use a uniquely named node."
If servers.Count > 1 Then Fail "selecting server", "The EGP has multiple SAS servers. Set server_program to choose its connection."
root.setAttribute "server", sourceCode.Server

Stage "preparing"
Err.Clear
text = ReadAll(sasPath)
If Err.Number <> 0 Then Fail "preparing", "Cannot read submitted SAS source: " & Err.Description
Set code = project.CodeCollection.Add
code.Text = text
code.Server = sourceCode.Server
' Requested output formats must not depend on the user's current EG defaults.
code.UseApplicationOptions = False
code.GenHTML = wantHtml
code.GenListing = False
code.GenSasReport = False
code.GenPDF = False
code.GenRTF = False
If Err.Number <> 0 Then Fail "preparing", "Cannot configure the submitted program: " & Err.Description

Stage "running"
Err.Clear
code.Run
If Err.Number <> 0 Then Problem "error", "running", "Enterprise Guide execution failed: " & Err.Description
root.setAttribute "ran", "1"

' Always try to preserve the log and readable sibling outputs after a failure.
Stage "saving log"
Err.Clear
code.Log.SaveAs logPath
If Err.Number <> 0 Then Problem "error", "saving log", "Cannot save SAS log: " & Err.Description

If wantHtml Then
  Stage "exporting HTML"
  Err.Clear
  count = code.Results.Count
  If Err.Number <> 0 Then
    Problem "export-error", "html", "Cannot enumerate HTML results: " & Err.Description
  Else
    For n = 0 To count - 1
      Err.Clear
      Set item = code.Results.Item(n)
      label = CStr(n + 1) & "_" & CleanName(item.Name)
      path = "html\" & label
      fso.CreateFolder outDir & "\" & path
      If Err.Number <> 0 Then
        Problem "export-error", "html", "Cannot prepare result " & CStr(n + 1) & ": " & Err.Description
      Else
        ExportItem item, "html", path & "\index.html"
      End If
    Next
  End If
End If
If wantTables Then
  Stage "exporting tables"
  Err.Clear
  count = code.OutputDatasets.Count
  If Err.Number <> 0 Then
    Problem "export-error", "table", "Cannot enumerate output tables: " & Err.Description
  Else
    For n = 0 To count - 1
      Err.Clear
      Set item = code.OutputDatasets.Item(n)
      label = CStr(n + 1) & "_" & CleanName(item.Name)
      If Err.Number <> 0 Then
        Problem "export-error", "table", "Cannot read output table " & CStr(n + 1) & ": " & Err.Description
      Else
        ExportItem item, "table", "tables\" & label & "." & tableFormat
      End If
    Next
  End If
End If
Stage "closing"
Finish 0
'''


def _decode(raw: bytes, encoding: str | None = None) -> str:
    if raw.startswith(b"\x00MSMAMARPCRYPT"):
        raise ValueError("The SAS file is encrypted/protected; supply readable SAS source.")
    if encoding is None:
        if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            encoding = "utf-16"
        elif raw.startswith(codecs.BOM_UTF8):
            encoding = "utf-8-sig"
        else:
            sample = raw[:4096]
            even, odd = sample[::2], sample[1::2]
            if even and odd and odd.count(0) / len(odd) > .3 and even.count(0) / len(even) < .1:
                encoding = "utf-16-le"
            elif even and odd and even.count(0) / len(even) > .3 and odd.count(0) / len(odd) < .1:
                encoding = "utf-16-be"
            else:
                try:
                    return raw.decode("utf-8")
                except UnicodeDecodeError:
                    encoding = "cp1252"
    return raw.decode(encoding).lstrip("\ufeff")


def _require_windows() -> None:
    if os.name != "nt":
        raise OSError("SAS execution requires Windows with SAS Enterprise Guide installed.")


def _launch_worker(request: Path, output) -> subprocess.Popen:
    # A separate real, hidden console preserves the working terminal semantics
    # even when the caller is pythonw, a notebook, or a future UI process.
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    python = Path(sys.executable).with_name("python.exe")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    return subprocess.Popen([str(python), "-u", str(Path(__file__).resolve()), "--worker", str(request)],
                            cwd=request.parent, stdin=None, stdout=output, stderr=subprocess.STDOUT,
                            env=env, creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup)


def _stop_worker(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        stopped = subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                                 capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        if stopped.returncode and process.poll() is None:
            raise RuntimeError(f"Could not stop engine worker PID {process.pid}. Check its run state.")
    else:  # Enables real subprocess lifecycle tests on development platforms.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # The worker finished between the poll and stop request.
    process.wait(timeout=10)


def _prepare_console() -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetConsoleWindow.restype = wintypes.HWND
    kernel.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
    kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    if not kernel.GetConsoleWindow():
        raise RuntimeError("The engine worker has no Windows console; SAS was not started.")
    fd = os.open("CONIN$", os.O_RDWR)
    try:
        os.dup2(fd, 0)
    finally:
        if fd != 0:
            os.close(fd)
    handle = msvcrt.get_osfhandle(0)
    if not kernel.SetStdHandle(-10 & 0xffffffff, handle):
        raise ctypes.WinError(ctypes.get_last_error())
    mode = wintypes.DWORD()
    if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
        raise RuntimeError("The engine worker's input is not a Windows console.")
    kernel.SetConsoleMode(handle, (mode.value | 0x80) & ~0x40)


def _worker(request_path: Path) -> int:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    root = request_path.parent
    _prepare_console()
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    host = windir / "SysWOW64/cscript.exe"
    if not host.is_file():
        host = windir / "System32/cscript.exe"
    if not host.is_file():
        raise FileNotFoundError("Windows cscript.exe is unavailable.")
    command = [str(host), "//nologo", "//U", str(root / "_bridge.vbs"), request["egp_path"],
               str(root / "submitted.sas"), str(root), str(int(request["export_html"])),
               str(int(request["export_tables"])), request["table_format"], request["server_program"] or ""]
    with (root / "console.txt").open("wb", buffering=0) as output:
        # Do not use PIPE, DEVNULL or a different console for this child.
        child = subprocess.Popen(command, cwd=root, stdin=None, stdout=output, stderr=subprocess.STDOUT,
                                 creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        return child.wait()


def _collect(root: Path, request: dict, elapsed: float, returncode: int | None,
             failure: str | None, timed_out: bool, cancelled: bool = False) -> RunResult:
    errors, warnings, exports, html, tables = [], [], [], [], []
    server = None
    if failure:
        errors.append(failure)
    try:
        report = ET.parse(root / "_automation.xml").getroot()
        server = report.get("server")
        if report.tag != "run" or report.get("complete") != "1" or report.get("ran") != "1":
            errors.append("Enterprise Guide did not report a completed run.")
        errors.extend(f"{node.get('phase')}: {node.text or 'Unknown automation error'}" for node in report.findall("error"))
        exports.extend(f"{node.get('phase')}: {node.text or 'Unknown export error'}" for node in report.findall("export-error"))
        for node in report.findall("output"):
            kind, relative = node.get("kind"), node.get("path", "")
            folder = root / ("html" if kind == "html" else "tables")
            path = (root / relative).resolve()
            if kind not in {"html", "table"} or not path.is_relative_to(folder) or not path.is_file():
                exports.append("Invalid or missing exported file: " + relative)
                continue
            if kind == "html":
                with path.open("rb") as source:
                    sample = source.read(65536).replace(b"\x00", b"").lstrip(b"\xef\xbb\xbf\xff\xfe \t\r\n")
                if not sample.startswith(b"<") or not re.search(rb"(?i)<(?:!doctype\s+html\b|html\b)", sample):
                    exports.append("Result is not HTML: " + relative)
                    continue
                html.append(path)
            else:
                if request["table_format"] == "xlsx":
                    try:
                        with zipfile.ZipFile(path) as workbook:
                            if "xl/workbook.xml" not in workbook.namelist():
                                raise ValueError("Missing workbook.xml")
                    except (OSError, ValueError, zipfile.BadZipFile):
                        exports.append("Result is not an XLSX workbook: " + relative)
                        continue
                tables.append(path)
    except (OSError, ET.ParseError) as exc:
        errors.append("Automation result is missing or unreadable: " + str(exc))
    log_path = root / "sas.log"
    try:
        log = _decode(log_path.read_bytes())
    except (OSError, UnicodeError, ValueError) as exc:
        log = ""
        errors.append("SAS log is missing or unreadable: " + str(exc))
    sas_errors = re.findall(r"(?mi)^[ \t]*ERROR(?:\s+\d+-\d+)?:[^\r\n]*", log)
    warnings.extend(re.findall(r"(?mi)^[ \t]*WARNING(?:\s+\d+-\d+)?:[^\r\n]*", log))
    if returncode not in {0, None}:
        errors.append(f"Automation worker exited with code {returncode}.")
    status = "CANCELLED" if cancelled else "TIMED_OUT" if timed_out else "FAILED" if errors else "SAS_ERROR" if sas_errors else "EXPORT_ERROR" if exports else "SUCCESS"
    result = RunResult(status, root, log, log_path, tuple(html), tuple(tables), root / "submitted.sas",
                       root / "console.txt", elapsed, returncode, server, tuple([*errors, *sas_errors, *exports]), tuple(warnings))
    summary = dict(request, status=status, elapsed_seconds=elapsed, returncode=returncode, server=server,
                   log_path=str(log_path), html_files=[str(p) for p in html], table_files=[str(p) for p in tables],
                   errors=result.errors, warnings=result.warnings)
    (root / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def run_sas(egp_path: str | Path, sas_path: str | Path, output_dir: str | Path, *,
            export_html: bool = True, export_tables: bool = False, table_format: str = "xlsx",
            server_program: str | None = None, encoding: str | None = None,
            timeout: float | None = None, cancel_file: str | Path | None = None) -> RunResult:
    """Run exactly one supplied SAS file and return its log, output paths and status.

    The log is always captured. HTML and output-table exports are optional;
    tables are individual XLSX or CSV files, not in-memory data frames.
    output_dir must be new or empty. EGP/SAS inputs are never overwritten.
    server_program names an existing EGP code node whose server to inherit;
    choose one explicitly if the EGP contains multiple SAS servers.

    Invalid inputs raise before SAS starts. Execution/SAS/export failures return
    a non-success RunResult, preserving available outputs. timeout covers opening,
    running, export and closing; it stops this run's local worker tree. A remote
    server job might require separate cancellation. There is no automatic retry.
    """
    egp, sas, root = (Path(value).expanduser().resolve() for value in (egp_path, sas_path, output_dir))
    for path, suffix in ((egp, ".egp"), (sas, ".sas")):
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.suffix.casefold() != suffix:
            raise ValueError(f"Expected a {suffix} file: {path}")
    if type(export_html) is not bool or type(export_tables) is not bool:
        raise ValueError("export_html and export_tables must be booleans.")
    if table_format not in {"xlsx", "csv"}:
        raise ValueError("table_format must be 'xlsx' or 'csv'.")
    if server_program is not None and (not isinstance(server_program, str) or not server_program.strip() or any(ord(c) < 32 for c in server_program)):
        raise ValueError("server_program must be a non-empty EGP code-node name.")
    if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError("timeout must be a positive, finite number of seconds, or None.")
    if cancel_file is not None and not isinstance(cancel_file, (str, os.PathLike)):
        raise ValueError("cancel_file must be a filesystem path or None.")
    cancellation = Path(cancel_file).expanduser().resolve() if cancel_file is not None else None
    if cancellation is not None and cancellation.exists() and not cancellation.is_file():
        raise ValueError("cancel_file must point to a file, not a directory.")
    original = sas.read_bytes()
    text = _decode(original, encoding)
    _require_windows()
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".engine.lock"
    with lock.open("x"):
        pass
    process = None
    interrupted = False
    started = time.perf_counter()
    try:
        if any(path != lock for path in root.iterdir()):
            raise FileExistsError("Use a new or empty output folder; existing outputs are preserved: " + str(root))
        request = dict(egp_path=str(egp), sas_path=str(sas), export_html=export_html,
                       export_tables=export_tables, table_format=table_format, server_program=server_program,
                       started=datetime.now(timezone.utc).isoformat())
        (root / "source.sas").write_bytes(original)
        (root / "submitted.sas").write_text(text, encoding="utf-8", newline="")
        (root / "_bridge.vbs").write_text(_VBS, encoding="utf-16")
        (root / "request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
        for folder in ("html", "tables"):
            (root / folder).mkdir()
        failure, timed_out, returncode, cancelled = None, False, None, False
        with (root / "worker.txt").open("wb", buffering=0) as worker_output:
            try:
                if cancellation is not None and cancellation.is_file():
                    cancelled = True
                    failure = "Cancelled before SAS started."
                else:
                    process = _launch_worker(root / "request.json", worker_output)
                if cancelled:
                    pass
                elif cancellation is None:
                    returncode = process.wait(timeout=timeout)
                else:
                    deadline = time.monotonic() + timeout if timeout is not None else None
                    while process.poll() is None:
                        if cancellation.is_file():
                            cancelled = True
                            failure = "Cancellation requested; local automation stopped. Verify remote SAS session state."
                            _stop_worker(process)
                            break
                        if deadline is not None and time.monotonic() >= deadline:
                            raise subprocess.TimeoutExpired(process.args, timeout)
                        time.sleep(.1)
                    returncode = process.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                failure = f"Timeout after {timeout:g} seconds; local automation stopped. Verify remote SAS session state."
                _stop_worker(process)
                returncode = process.returncode
            except KeyboardInterrupt:
                interrupted = True
                failure = "Interrupted by caller."
                if process is not None:
                    _stop_worker(process)
                returncode = process.returncode if process is not None else None
            except OSError as exc:
                failure = "Cannot start automation worker: " + str(exc)
        result = _collect(root, request, time.perf_counter() - started, returncode, failure, timed_out, interrupted or cancelled)
        if interrupted:
            raise KeyboardInterrupt
        return result
    finally:
        if process is not None and process.poll() is None:
            _stop_worker(process)
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        try:
            sys.exit(_worker(Path(sys.argv[2]).resolve()))
        except Exception:
            traceback.print_exc()
            sys.exit(1)
    else:
        print("Import run_sas from engine, then call run_sas(egp_path, sas_path, output_dir).")
