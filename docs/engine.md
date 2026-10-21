# Independent execution engine

`engine.py` is a separate, standard-library-only Python 3.10+ module with one public execution function. It does not import `pysas.py`, read Workbench settings, start a watcher, resolve dependencies or prepend `_*.sas` files. The Run stream tab composes a program above this boundary and calls it through a separate worker. The existing Run, watcher and scheduler keep their execution path. This module is included in the Workbench ZIP and can also be copied on its own.

## Call it

Copy `engine.py` beside your Python calling script, on a Windows PC with SAS Enterprise Guide and its existing SAS connection configured:

```python
from engine import run_sas

result = run_sas(
    egp_path=r"C:\SAS\connection.egp",
    sas_path=r"C:\SAS\extract.sas",
    output_dir=r"C:\SAS\outputs\test_001",  # new or empty folder
    export_html=True,
    export_tables=True,
    table_format="xlsx",                   # or "csv"
)

print(result.status, result.elapsed_seconds)
print(result.log)                          # full SAS log text
print(result.log_path)                     # saved SAS log
print(result.html_files)                   # tuple of HTML paths
print(result.table_files)                  # tuple of exported table paths
print(result.errors, result.warnings)
```

For a first real test, use the provided `examples/engine_smoke.sas`. It creates a small WORK table and runs PRINT and MEANS. Use an EGP containing a code node connected to your intended SAS server. The smoke program needs no application-specific libraries or parameters.

## Parameters

| Parameter | Default | Behavior |
|---|---|---|
| `egp_path` | required | Existing EGP used for the Enterprise Guide/SAS connection. |
| `sas_path` | required | Existing readable SAS file to submit. |
| `output_dir` | required | New or empty folder. Existing results are never overwritten. |
| `export_html` | `True` | Request HTML generation and save available HTML results. |
| `export_tables` | `False` | Export datasets that EG exposes through this program's OutputDatasets collection. |
| `table_format` | `"xlsx"` | One Excel workbook per output table; `"csv"` selects CSV instead. No pandas or openpyxl dependency. |
| `server_program` | `None` | Name of an existing EGP code node whose Server connection to inherit. Required when the EGP has multiple different SAS servers. That node's code is not submitted by the engine. |
| `encoding` | `None` | Source decoding override, for example `"cp1252"`. Default detects UTF-8/BOM, UTF-16 and legacy Windows Western text. |
| `timeout` | `None` | Optional positive seconds covering opening, running, exporting and closing. No automatic timeout or retry by default. |
| `cancel_file` | `None` | Optional path to a caller-owned cancellation marker. When present, stop this call's local worker tree and return `CANCELLED`. |

The SAS log is always saved and returned, including when HTML/tables are disabled. Data-only programs can legitimately return no HTML, and programs that create no datasets can return no tables.

The engine passes the supplied source text without adding setup code, SAS macro variables, shared WORK, ODS statements or custom macro wrappers. Enterprise Guide can still add its normal generated connection/ODS wrapper according to the requested output options. The caller is responsible for preparing a complete SAS program. The original source bytes are retained as `source.sas`; the decoded UTF-8 submission is retained as `submitted.sas`. Initialization discovery and scheduling can be built above this function later.

The engine opens the EGP, creates one new code object, assigns the selected existing connection and runs that new object. It does not call Project.Run, run a process flow or submit the existing code nodes itself. Server/session startup and EGP autoexec behavior configured in Enterprise Guide still belong to that environment; use an appropriate connection/template project.

HTML generation is explicitly selected through the code object's output settings instead of relying on the user's current EG output defaults. Result exports use EG's own SaveAs operations. Each HTML result gets its own subfolder to avoid filename/asset collisions; keep any accompanying assets with that folder. Source code that explicitly overrides ODS destinations can still affect what EG produces. A saved non-HTML result is reported as an export error rather than returned as a valid HTML file.

Output tables mean SAS datasets reported by EG for this submitted program. They are distinct from the procedure tables rendered inside an HTML report. The engine does not scan every library or convert every ODS table into a SAS dataset.

## Return value and failures

`RunResult` contains status, success, output folder, full log text/path, HTML/table paths, submitted-code path, automation-console path, elapsed seconds, worker exit code, chosen SAS server, errors and warnings. Output tables are returned as file paths, not loaded into memory.

| Status | Meaning |
|---|---|
| `SUCCESS` | Automation completed, the log was saved, no SAS errors were detected, and requested exports had no reported failures. |
| `SAS_ERROR` | SAS log contains error diagnostics; available outputs remain accessible. |
| `EXPORT_ERROR` | SAS completed, but one or more requested outputs could not be saved or validated. Readable siblings are retained and returned. |
| `FAILED` | Automation, connection, log-saving or completion reporting failed. |
| `TIMED_OUT` | The configured time limit expired; local automation was stopped. |
| `CANCELLED` | A cancellation marker or caller KeyboardInterrupt stopped local automation. A marker returns this result; KeyboardInterrupt saves it, then is re-raised. |

Failure precedence is cancellation/timeout, then automation/log failure, then SAS errors, then export errors. All recorded error details are retained even when more than one category applies. Warnings alone do not make a run fail.

Invalid paths, parameter types, encoding/protected-source problems, unsupported platforms and non-empty output folders raise before SAS starts. Inability to stop a worker or write to the output filesystem can also raise; do not treat an exception as a successful run. Once a run is started, ordinary SAS/automation/export failures return a non-success result and preserve available evidence. There are no automatic retries that might repeat a data-changing program.

The output folder contains `sas.log`, `html/`, `tables/`, `source.sas`, `submitted.sas`, `result.json` and diagnostic request/bridge/console files. A file is returned in `html_files` or `table_files` only after a successful export record and basic content validation; missing, partial or incorrectly typed artifacts are not presented as successful exports. Unreturned partial artifacts remain in the folder for inspection.

Each call owns a separate hidden Python console worker and cscript process. It restores real Windows console input before starting Enterprise Guide, following the console semantics that resolved the old UI hangs. Console output goes to files rather than pipes, so the caller does not need to drain output for the run to finish. Timeout/interrupt targets only that worker's local process tree. A job on a remote SAS server can outlive termination of local automation; remote cancellation is not guaranteed by this function.

This is a blocking execution function, not a live-log API. If it is stopped while SAS is still running remotely, Enterprise Guide might not have exported a SAS log yet; `result.log` can then be empty, with the missing log reported in `errors`.

## Validation

Run the isolated tests:

```console
python -m unittest discover -s tests -p test_standalone_engine.py -v
```

Cross-platform tests exercise the real Python subprocess lifecycle, exact source snapshots, independent output options, log decoding, SAS/error/export statuses, retained siblings, missing evidence, large console output and timeout cleanup. They substitute the SAS worker.

Windows-specific tests run the real hidden worker and cscript with substitute EG COM objects, covering server binding, submitted code, HTML, XLSX/CSV, output flags and failures. Those checks are skipped on macOS/Linux. The target Windows/Enterprise Guide/SAS environment is still required to verify real COM registration, authentication, HTML assets and server-side execution. The release workflow runs these checks on Windows, macOS and Linux; Windows COM substitutes do not replace target-environment SAS acceptance.

The implementation follows the existing working PySAS bridge and the operations/output options described in SAS's [Enterprise Guide automation paper](https://support.sas.com/resources/papers/proceedings12/298-2012.pdf). SAS also provides an [automation reference archive](https://support.sas.com/documentation/onlinedoc/guide/SASEGScripting42.zip) for checking installed-version behavior. This is an independent implementation of that small execution boundary, not an import of the scheduler or UI.
