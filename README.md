# PySAS Toolkit

**PySAS 0.3.2** is a single-file, Windows-focused command-line toolkit for automating repeatable SAS Enterprise Guide workflows.

It grew out of day-to-day model-development and consulting work where large SAS processes were difficult to inspect, rerun, parallelise, move between environments and review consistently. The current implementation brings those workflows together in one portable `pysas.py` utility.

## Current status

PySAS is now an implemented working toolkit rather than a design-only repository.

| Component | Status in 0.3.2 | What it does |
| --- | --- | --- |
| SAS bundle utility | Implemented | Pack, verify and safely unpack SAS source trees with SHA-256 integrity metadata and backups |
| EGP tools | Implemented | Inspect EGP archives, extract embedded SAS programs and conservatively repack them into an EGP template |
| Standalone runner | Implemented | Run a SAS file through SAS Enterprise Guide automation with shared init code, logs and results |
| Watch-folder runner | Implemented | Watch an inbox, execute stable `.sas` files concurrently and keep timestamped run folders |
| Table extraction | Implemented | Automatically export output datasets to one Excel workbook for `.tables.sas` jobs or `--tables` runs |
| Excel dependency scheduler | Implemented | Run EGP programs according to dependencies, skip/error rules and a parallelism limit |
| Schedule continuation | Implemented | Resume a prior schedule while automatically skipping tasks that already completed successfully |

## Requirements

PySAS 0.3.2 is designed for controlled Windows environments with:

- Python 3.9+ recommended;
- SAS Enterprise Guide installed and configured for the target SAS environment;
- access to the SAS Enterprise Guide COM automation interface;
- Windows Script Host / `cscript.exe`;
- `openpyxl` for scheduler and table-workbook functionality.

Install the Python dependency with:

```powershell
py -m pip install openpyxl
```

`rich` is optional.

The SAS server connection, credentials, libraries and permissions remain environment-specific and are not included in this repository.

## Installation

The toolkit is intentionally portable: place `pysas.py` beside the EGP project, scheduler workbook and any shared top-level SAS initialisation files you want it to use.

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

## Command overview

Running the script with no arguments prints the local workspace summary and common commands.

```powershell
py pysas.py
```

Main command groups:

```powershell
py pysas.py bundle ...
py pysas.py egp ...
py pysas.py runner ...
py pysas.py schedule ...
```

## 1. SAS code bundles

The bundle engine creates a portable text representation of SAS source files with per-file SHA-256 hashes and a manifest checksum.

```powershell
# Pack top-level SAS files
py pysas.py bundle pack

# Include SAS files recursively
py pysas.py bundle pack --recursive

# Validate a bundle and compare it with local source
py pysas.py bundle verify

# Restore changed or missing files
py pysas.py bundle unpack
```

Before replacing existing source files, unpacking creates timestamped backups under `_codebase_backups/` unless `--no-backup` is explicitly supplied. Paths inside bundles are validated to prevent absolute-path or `..` traversal outside the working directory.

## 2. EGP inspection and round-tripping

Enterprise Guide projects are ZIP-based artifacts. PySAS provides conservative helpers for inspecting and editing the embedded SAS source without rebuilding unrelated project content from scratch.

```powershell
# Inspect the EGP beside pysas.py
py pysas.py egp inspect

# Inspect an explicit project
py pysas.py egp inspect project.egp

# Extract embedded SAS programs
py pysas.py egp extract project.egp

# Repack edited extracted programs into an EGP template
py pysas.py egp pack project --template project.egp --output project_updated.egp
```

Extraction writes a `.pysas_egp_manifest.json` mapping the extracted source files back to their original archive members. Repacking replaces only those mapped SAS members in the template and preserves the rest of the archive.

Because EGP internals are SAS Enterprise Guide version-sensitive, use copies of important projects and validate the rebuilt artifact in your target environment.

## 3. Standalone SAS runner

Run a standalone `.sas` file through Enterprise Guide automation:

```powershell
py pysas.py runner run diagnostic.sas
```

Useful options:

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

automatically enables table export. Output datasets reported by Enterprise Guide are exported and combined into one Excel workbook inside that run's `results` folder. The same behaviour can be requested explicitly with `--tables`.

## 4. Watch-folder runner

Start the watcher with:

```powershell
py pysas.py runner watch
```

The watcher creates and uses:

```text
runner/
|-- inbox/
|-- claimed/
`-- runs/
```

Drop `.sas` files into `runner\inbox`. PySAS waits until the file appears stable, claims it atomically, and executes jobs with a configurable worker pool.

```powershell
py pysas.py runner watch --workers 3
py pysas.py runner watch --poll 2
```

The terminal dashboard shows currently running jobs and elapsed time, the most recent runs ready for review, and queued inbox files. Running jobs are allowed to finish when the watcher is stopped with `Ctrl+C`.

## 5. Excel dependency scheduler

The scheduler reads an Excel workbook, using a worksheet named `Schedule` when present (otherwise the first worksheet).

Required columns are:

| Column | Purpose |
| --- | --- |
| `task_id` | Unique task identifier |
| `program` | EGP program/code item to run |
| `depends_on` | Comma-separated prerequisite task IDs |
| `skip` | Mark the task as successfully skipped |
| `row_start` | Optional first SAS source line to run |
| `row_end` | Optional last SAS source line to run |
| `section` | Free-form grouping metadata |
| `stop_process_on_error` | Prevent additional normal tasks from being launched after failure |
| `stop_program_on_error` | Reserved control field carried with task metadata |
| `max_parallel` | Parallelism setting used to derive the worker limit |
| `always_run` | Allow the task to run after a dependency failure, useful for cleanup/finalisation |

Run the schedule with:

```powershell
py pysas.py schedule
```

Or identify inputs explicitly:

```powershell
py pysas.py schedule --workbook Schedule.xlsx --project project.egp --workers 4
```

The scheduler validates duplicate IDs, unknown dependencies and invalid row ranges before execution. Eligible tasks run concurrently once their dependencies have completed. Each task receives an isolated copy of the EGP project and its own output directory.

Every schedule run produces a timestamped `runs/...__schedule` folder and summaries in:

- `run_summary.csv`
- `run_summary.txt`
- `run_summary.xlsx`

### Continuing a previous run

A previous scheduler run can be continued with:

```powershell
py pysas.py schedule continue runs\20260908_120000__schedule
```

PySAS reads the prior summary, temporarily marks previously successful tasks as skipped, and launches a new isolated schedule run for the remaining work.

## Enterprise Guide automation

PySAS drives SAS Enterprise Guide through the Windows COM automation object model. The current implementation tries the Enterprise Guide 8.1 automation object and falls back to 7.1. It prefers the 32-bit `cscript.exe` under `SysWOW64` when available, otherwise the system `cscript.exe`.

This means PySAS is not a replacement for a SAS installation or SAS server. It is an automation layer around an already working Enterprise Guide environment.

## Design principles

The implementation deliberately favours safety and reviewability:

- source material is preserved by default;
- EGP repacking starts from a template rather than generating arbitrary project internals;
- bundle paths are validated before writing files;
- bundle restoration creates backups before replacement;
- file replacement uses temporary files and atomic `os.replace` operations;
- runner and scheduler executions are isolated in timestamped run folders;
- logs, submitted code, console output and machine-readable summaries are retained;
- watcher jobs are claimed before execution to reduce duplicate processing.

## Limitations

PySAS is currently a practical Windows/SAS Enterprise Guide automation toolkit rather than a cross-platform SAS API.

Important limitations include:

- Enterprise Guide COM automation must be available locally;
- EGP archive structure can vary across Enterprise Guide versions;
- table export depends on Enterprise Guide exposing output datasets through the automation model;
- `stop_program_on_error` is part of the scheduler schema in 0.3.2 but is not yet used to alter execution behaviour independently;
- scheduler dependency cycles are surfaced as unresolved/blocked tasks during execution rather than by a separate pre-run graph-cycle algorithm;
- automated Windows/Enterprise Guide integration tests are not yet included in the public repository.

## Version

Current published implementation: **0.3.2**.

The version is also embedded directly in the script:

```powershell
py pysas.py version
```

## Repository hygiene

Do not commit proprietary SAS programs, client data, credentials, server names, internal library paths or production EGP projects. Use sanitised examples when demonstrating workflows.

## License

No license has been selected yet. Until a license file is added, the repository is publicly viewable but no reuse rights are granted.
