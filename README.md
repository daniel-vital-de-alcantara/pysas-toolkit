# PySAS Toolkit

**PySAS 0.3.12** is a single-file, Windows-focused command-line toolkit for automating repeatable SAS Enterprise Guide workflows.

It grew out of day-to-day model-development and consulting work where large SAS processes were difficult to inspect, rerun, parallelise, move between environments and review consistently. The current implementation brings those workflows together in one portable `pysas.py` utility.

## What it does

| Component | Status in 0.3.12 | Purpose |
| --- | --- | --- |
| SAS bundle utility | Implemented | Pack, verify and safely unpack SAS source trees with SHA-256 integrity metadata and backups |
| EGP tools | Implemented | Inspect EGP archives, extract embedded SAS programs and conservatively repack them into an EGP template |
| Standalone runner | Implemented | Run a SAS file through SAS Enterprise Guide automation with shared init code, logs and results |
| Watch-folder runner | Implemented | Watch an inbox, execute stable `.sas` files concurrently and keep timestamped run folders |
| Table extraction | Implemented | Export output datasets to one Excel workbook for `.tables.sas` jobs or `--tables` runs |
| Excel dependency scheduler | Implemented | Run EGP programs according to dependencies, skip/error rules and a parallelism limit |
| Schedule continuation | Implemented | Resume a prior schedule while automatically skipping tasks that already completed successfully |

## Local UI preview

The **PySAS Workbench** adds a local browser interface around the standalone `pysas.py` engine. It includes live running filenames and elapsed time, completed-run
history, a runner and watcher, schedules with per-task clocks, bundle/EGP tools,
and a log/code/results inspector.

Download the **Python ZIP** from [GitHub Releases](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/releases),
extract it completely, put your SAS/EGP/workbook files beside `pysas.py`, and
double-click **START_PYSAS.bat**. On Windows, PySAS opens in a dedicated app
window using Edge or Chrome, without tabs or an address bar.
**START_PYSAS_BROWSER.bat** retains the normal-browser option. Requires Python 3.10+ and your existing Windows /
Enterprise Guide setup; `openpyxl` is required for Excel features. No Node.js or
frontend installation is needed.

See [START_HERE.txt](START_HERE.txt) and the [workbench guide](docs/ui-workbench.md).
The command-line toolkit is version 0.3.12; the UI preview is 0.4.0-preview.19.

## Requirements

PySAS 0.3.12 is designed for controlled Windows environments with:

- Python 3.9+ recommended;
- SAS Enterprise Guide installed and configured for the target SAS environment;
- access to the SAS Enterprise Guide COM automation interface;
- Windows Script Host / `cscript.exe`;
- `openpyxl` for scheduler and table-workbook functionality.

Install the Python dependency with:

```powershell
py -m pip install openpyxl
```

`rich` is optional. SAS server connections, credentials, libraries and permissions remain environment-specific and are not included in this repository.

## Installation

Place `pysas.py` beside the EGP project, scheduler workbook and any shared top-level SAS initialisation files you want it to use.

```text
workspace/
|-- pysas.py
|-- project.egp
|-- Schedule.xlsx
|-- _00_libraries.sas
|-- _10_macros.sas
|-- diagnostic.sas
`-- runner/
```

All files matching `_*.sas` beside `pysas.py` are automatically prepended to standalone runner jobs in alphabetical order.

Check the installed version with:

```powershell
py pysas.py --version
```

Running the script with no arguments prints the local workspace summary and common commands:

```powershell
py pysas.py
```

## 1. SAS code bundles

The bundle engine creates a portable text representation of SAS source files with per-file SHA-256 hashes and a manifest checksum.

```powershell
py pysas.py bundle pack
py pysas.py bundle pack --recursive
py pysas.py bundle verify
py pysas.py bundle unpack
```

Set a code folder explicitly when working outside the script directory:

```powershell
py pysas.py bundle pack --root "C:\Projects\Model A" --recursive
py pysas.py bundle verify --root "C:\Projects\Model A"
py pysas.py bundle unpack --root "C:\Projects\Model A"
```

Without `--root`, existing commands still use the folder beside `pysas.py`.
The UI's Bundles panel lets you save frequently used code folders and switch
between them. Relative bundle/output filenames use the selected code folder.
Saved paths and the last-used folder persist per workspace.

Before replacing existing source files, unpacking creates timestamped backups under `_codebase_backups/` unless `--no-backup` is explicitly supplied. Bundle paths are validated to prevent absolute-path or `..` traversal outside the working directory.

## 2. EGP inspection and round-tripping

Enterprise Guide projects are ZIP-based artifacts. PySAS provides conservative helpers for inspecting and editing embedded SAS source without rebuilding unrelated project content from scratch.

```powershell
py pysas.py egp inspect
py pysas.py egp inspect project.egp
py pysas.py egp extract project.egp
py pysas.py egp pack project --template project.egp --output project_updated.egp
```

Extraction writes a `.pysas_egp_manifest.json` mapping extracted source files back to their original archive members. Repacking replaces only those mapped SAS members in the template and preserves the rest of the archive.

Because EGP internals are SAS Enterprise Guide version-sensitive, use copies of important projects and validate rebuilt artifacts in the target environment.

## 3. Standalone SAS runner

Run a standalone `.sas` file through Enterprise Guide automation:

```powershell
py pysas.py runner run diagnostic.sas
```

Useful options include:

```powershell
py pysas.py runner run diagnostic.sas --template project.egp
py pysas.py runner run diagnostic.sas --lib _libraries.sas
py pysas.py runner run diagnostic.sas --tables
py pysas.py runner run diagnostic.sas --no-notify
```

Each run receives its own timestamped directory containing submitted code, logs, console output, generated results and a status file. SAS log lines beginning with `ERROR` are detected and reported as SAS errors even when the automation process itself exits normally.

### Automatic table workbooks

A source file named like:

```text
portfolio_checks.tables.sas
```

automatically enables table export. Output datasets reported by Enterprise Guide are combined into one Excel workbook inside that run's `results` folder. The same behaviour can be requested explicitly with `--tables`.

## 4. Watch-folder runner

Start the watcher with:

```powershell
py pysas.py runner watch
```

Choose optional input folders from **Files & folders** in the UI, or from the
single-file CLI:

```powershell
py pysas.py runner watch --inbox "C:\Jobs\Inbox" --init-dir "C:\Jobs\Shared"
py pysas.py runner run diagnostic.sas --init-dir "C:\Jobs\Shared"
```

Files named `_*.sas` in the shared initialization folder **and in the watcher
inbox** are prepended to each watched job in alphabetical filename order.
They remain in place and are never claimed as jobs. Without `--init-dir`, the
shared folder is the folder beside `pysas.py`. `--lib` still overrides the shared
list with the explicitly selected file. Upload shared files before job files.

The watcher creates and uses:

```text
runner/
|-- inbox/
|-- claimed/
`-- runs/
```

Drop `.sas` files into `runner\inbox`. PySAS waits until the file appears stable, claims it atomically and executes jobs with a configurable worker pool.

```powershell
py pysas.py runner watch --workers 3
py pysas.py runner watch --poll 2
```

The terminal dashboard shows currently running jobs and elapsed time, the most recent runs ready for review and queued inbox files. Running jobs are allowed to finish when the watcher is stopped with `Ctrl+C`.

## 5. Excel dependency scheduler

The scheduler reads an Excel workbook, using a worksheet named `Schedule` when present and otherwise the first worksheet.

A fully sanitized example is included in [`examples/schedule_example.csv`](examples/schedule_example.csv), with field definitions and dependency guidance in [`docs/scheduler-schema.md`](docs/scheduler-schema.md). Open the CSV in Excel and save it as `Schedule.xlsx` to use it as a starting template.

The scheduler supports:

- explicit task dependencies;
- parallel execution of eligible tasks;
- skip flags that preserve all prerequisite dependencies;
- named section selection or inclusive source row ranges;
- process-level stop-on-error behaviour;
- always-run shared setup prepended before every scheduled program in the same SAS session;
- schedule continuation from a previous run;
- Stop schedule in the UI to cancel its active files and prevent new launches.

Run a schedule with:

```powershell
py pysas.py schedule
```

Or identify inputs explicitly:

```powershell
py pysas.py schedule --workbook Schedule.xlsx --project project.egp --workers 4
```

The scheduler validates IDs, dependencies, cycles, section/range conflicts and row bounds before execution. Named sections are extracted using the same markers as the Rich-terminal 0.3.2. Each submission inherits the target program’s SAS server. UI parallelism defaults to 10; the CLI honors workbook settings or defaults to 10. Shared setup error flags apply to the complete submission. Each task receives an isolated copy of the EGP project and its own output directory.

A skipped task waits for its parents before releasing downstream tasks. For
`A → B (skipped) → C`, C waits for A to succeed. This applies through any number
of skipped rows. **Stop schedule**, available on the schedule card and in its
Console view, stops that entire run; other schedules and watchers continue.

Every schedule run produces a timestamped `runs/...__schedule` folder with summaries in:

- `run_summary.csv`
- `run_summary.txt`
- `run_summary.xlsx`
- `schedule.log` — all available task SAS logs and console output, grouped in workbook order

Continue a previous run with:

```powershell
py pysas.py schedule continue runs\20260908_120000__schedule
```

PySAS reads the prior summary, temporarily marks previously successful normal tasks as skipped (shared setup stays enabled unless explicitly skipped in the workbook) and launches a new isolated schedule run for the remaining work.

## Files, uploads and keeping the PC awake

The **Files & folders** page saves separate locations for project inputs
(SAS/EGP/workbooks), shared initialization files, and the watcher inbox.
Stop active commands before changing folders. Results continue to use the
existing workspace run folders.

Select multiple files to upload to project inputs, initialization, the watcher
inbox, or the currently selected bundle code folder. Files are copied locally,
staged until complete, and existing filenames are rejected rather than replaced.
The upload limit is 512 MB per file. Uploading jobs to an active watcher may
start them immediately. Initialization uploads must be named `_*.sas`.

**Keep PC awake** uses Windows' [SetThreadExecutionState API](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate)
to prevent idle sleep and display timeout while enabled. It generates no input,
does not prevent manual sleep, lid-close behavior or organization lock policies,
and resets when the local server closes. It is not an autoclicker.

## Enterprise Guide automation

PySAS drives SAS Enterprise Guide through the Windows COM automation object model. The current implementation tries the Enterprise Guide 8.1 automation object and falls back to 7.1. It prefers the 32-bit `cscript.exe` under `SysWOW64` when available, otherwise the system `cscript.exe`.

PySAS is therefore not a replacement for a SAS installation or SAS server. It is an automation layer around an already working Enterprise Guide environment.

## Design principles

The implementation deliberately favours safety and reviewability:

- preserve source material by default;
- repack EGPs from a template rather than generating arbitrary project internals;
- validate paths before writing files;
- create backups before bundle restoration;
- use temporary files and atomic replacement where possible;
- isolate runner and scheduler executions in timestamped folders;
- retain logs, submitted code, console output and machine-readable summaries;
- claim watcher jobs before execution to reduce duplicate processing.

The repository also includes a `.gitignore` tuned to keep runtime artifacts, local EGP files, SAS datasets, temporary workbooks and common secrets out of source control.

## Limitations

PySAS is a practical Windows/SAS Enterprise Guide automation toolkit rather than a cross-platform SAS API.

Important limitations include:

- Enterprise Guide COM automation must be available locally;
- EGP archive structure can vary across Enterprise Guide versions;
- table export depends on Enterprise Guide exposing output datasets through the automation model;
- Windows tests exercise real cscript and a substitute for EG COM; actual SAS server execution requires a configured Enterprise Guide environment.

## Version

Current published implementation: **0.3.12**.

```powershell
py pysas.py version
```

## Repository hygiene

Do not commit proprietary SAS programs, client data, credentials, server names, internal library paths or production EGP projects. Use sanitized examples when demonstrating workflows.

## License

PySAS Toolkit is released under the [MIT License](LICENSE).
