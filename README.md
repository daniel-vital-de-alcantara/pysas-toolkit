# PySAS Toolkit

Windows-focused utilities for automating repeatable SAS Enterprise Guide workflows.

> [!IMPORTANT]
> This repository currently contains the project specification and documentation only. The utilities described below are planned components; no executable scheduler, bundler, EGP round-trip tool, or watch-folder runner has been published here yet.

## Purpose

PySAS Toolkit is intended to reduce the manual work around multi-program SAS Enterprise Guide processes. Its design focuses on four related jobs:

- extracting SAS programs from Enterprise Guide projects and rebuilding project artifacts;
- scheduling dependent SAS tasks in parallel from an Excel control sheet;
- packaging a directory of SAS source into one portable, verifiable text bundle; and
- watching a folder for `.sas` files, running shared setup code, and collecting outputs.

The toolkit is designed for controlled Windows environments where SAS Enterprise Guide is already installed and automation must work through the Enterprise Guide COM interface.

## Project status

| Component | Status | Intended role |
| --- | --- | --- |
| EGP extraction and round-tripping | Planned | Extract SAS code and metadata from `.egp` projects and support a controlled rebuild workflow. |
| Excel-driven parallel scheduler | Planned | Validate dependencies and run eligible tasks concurrently through Enterprise Guide automation. |
| Single-file bundle utility | Planned | Pack, verify, and unpack normalized SAS text with integrity checks and safe file handling. |
| Watch-folder autorunner | Concept | Detect `.sas` inputs, run `lib.sas` first, and collect logs and results. |

This table is the source of truth until working code and tests are added.

## Requirements

The planned automation targets:

- Windows;
- SAS Enterprise Guide installed and configured for the target SAS environment;
- access to the SAS Enterprise Guide COM automation interface;
- Windows Script Host, including the 32-bit host at `%WINDIR%\SysWOW64\cscript.exe` where required by the installed Enterprise Guide automation components;
- Microsoft Excel for authoring the scheduler workbook; and
- permission to create isolated run, log, and output directories.

Exact supported versions will be documented after the first tested implementation. A SAS server connection, credentials, libraries, and permissions remain environment-specific and are not supplied by this project.

## Planned components

### 1. EGP extraction and round-tripping

The EGP workflow is intended to make SAS code stored inside an Enterprise Guide project easier to inspect, version, and move between environments. The planned flow is:

1. read an `.egp` project as an archive;
2. extract embedded SAS programs and the metadata needed to identify them;
3. preserve a stable relationship between extracted files and their project entries;
4. allow source files to be edited outside Enterprise Guide; and
5. rebuild or update an EGP artifact without silently losing unrelated project content.

Round-tripping is inherently version-sensitive. The first implementation will need fixture projects from supported Enterprise Guide versions and explicit tests before it can be considered safe for production projects.

### 2. Excel-driven parallel scheduler

The scheduler is designed around an Excel worksheet named `Schedule`. Each row represents a task. The control model includes columns for:

- task identifier;
- dependency list;
- skip flag;
- row or task range;
- section;
- error-control behavior;
- maximum parallelism; and
- always-run behavior.

Before execution, the scheduler is intended to reject:

- duplicate task identifiers;
- dependencies that refer to unknown tasks; and
- dependency cycles.

Validated tasks would become eligible when their dependencies finish. The scheduler would invoke 32-bit `cscript.exe`, run VBScript that controls SAS Enterprise Guide through COM, and enforce the configured concurrency limit. Each invocation would use an isolated timestamped run directory and produce per-task EGP and log outputs. Error-control and always-run settings would determine whether downstream or cleanup tasks continue after a failure.

The precise workbook schema, accepted values, dependency syntax, and exit-code contract will be versioned alongside the implementation rather than inferred from this design note.

### 3. Single-file SAS bundle utility

The bundle utility is intended to be a self-contained command-line tool rooted at the directory containing the script—not the caller's current working directory. Its design includes:

- recursive or configurable source discovery;
- deterministic ordering and normalized SAS text;
- a JSON-marked text container;
- SHA-256 integrity metadata;
- relative-path validation that prevents traversal outside the destination;
- backups before replacement;
- atomic writes where the platform permits them; and
- `pack`, `verify`, and `unpack` commands.

The bundle format will be documented and versioned before compatibility guarantees are made.

### 4. Watch-folder autorunner

The autorunner is an early concept for simple folder-based workflows:

1. monitor an input directory for `.sas` files;
2. execute `lib.sas` before every submitted program;
3. run each program through the configured SAS/Enterprise Guide environment; and
4. collect logs, generated results, and run metadata in a predictable output area.

File readiness checks, retry behavior, duplicate detection, and failure quarantine still need to be specified.

## Target folder layout

The following is the proposed repository layout. It describes where future implementations should live; those paths do not yet exist.

```text
pysas-toolkit/
|-- README.md
|-- docs/
|   |-- scheduler-schema.md
|   |-- bundle-format.md
|   `-- egp-compatibility.md
|-- egp-tools/
|-- scheduler/
|   |-- examples/
|   `-- scripts/
|-- bundle/
|-- autorunner/
|-- tests/
`-- examples/
```

A runtime workspace is expected to follow a separate pattern so that source and generated artifacts do not mix:

```text
workspace/
|-- input/
|   |-- Schedule.xlsx
|   |-- lib.sas
|   `-- programs/
|-- runs/
|   `-- YYYYMMDD-HHMMSS/
|       |-- tasks/
|       |-- egp/
|       |-- logs/
|       `-- results/
`-- archive/
```

## Intended usage

The command names below illustrate the planned interface. They are not available yet.

```powershell
# Planned scheduler invocation
.\scheduler\run-schedule.ps1 -Workbook .\input\Schedule.xlsx

# Planned bundle lifecycle
.\bundle\pysas-bundle.exe pack   --source .\programs --output project-bundle.txt
.\bundle\pysas-bundle.exe verify --bundle project-bundle.txt
.\bundle\pysas-bundle.exe unpack --bundle project-bundle.txt --destination .\restored

# Planned watch-folder runner
.\autorunner\start-runner.ps1 -Input .\input -Output .\runs
```

## Safety principles

Future implementations should:

- default to preserving source material;
- create backups before replacing user-managed files;
- validate all paths before extraction or unpacking;
- write to temporary files and replace targets atomically;
- keep every scheduler run isolated and timestamped;
- retain per-task logs and machine-readable run status; and
- fail validation before launching SAS when the schedule is inconsistent.

## Roadmap

1. Publish and test the single-file bundle utility, including a documented bundle format.
2. Define the `Schedule` worksheet schema and provide a validated example workbook.
3. Implement the scheduler's dependency graph, cycle detection, and concurrency controls.
4. Add the VBScript/Enterprise Guide COM execution layer and fixture-based Windows tests.
5. Add EGP extraction fixtures and define supported Enterprise Guide versions.
6. Prototype the watch-folder runner after the execution layer is stable.

## Contributing

Issues and focused pull requests are welcome once the first component is published. Please avoid committing proprietary SAS programs, credentials, server names, or client data in examples and test fixtures.

## License

No license has been selected yet. Until a license file is added, the repository is publicly viewable but no reuse rights are granted.
