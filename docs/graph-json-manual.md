# PySAS graph JSON manual for people and AI assistants

Download this file in Graph → File → JSON guide for AI, or Settings → Defaults.
Give it to an AI together with the program paths, desired order, dependencies
and shared initialization code. Ask for a `.json` file using the authoring format
below. In PySAS, choose Graph → File → Restore JSON, then review and save the plan.

## A complete example to copy

```json
{
  "format": "pysas-task-graph-authoring-1",
  "name": "Daily extracts",
  "workers": 10,
  "egp": "C:/SAS/connection.egp",
  "shared_work": {"enabled": false, "path": "", "libref": "VDI"},
  "setup": [
    {
      "id": "Libraries",
      "name": "Libraries and cases",
      "rows": [
        {"source_kind": "file", "file": "C:/SAS/_libs.sas", "mode": "whole"},
        {"source_kind": "inline", "name": "Cases", "code": "%let case_ids=12,24;", "mode": "whole"}
      ]
    }
  ],
  "nodes": [
    {"id": "A", "name": "Extract", "x": 0, "y": 0,
     "rows": [{"source_kind": "file", "file": "C:/SAS/extract.sas", "mode": "section", "sections": ["Realised", "Summary"]}],
     "export_html": true, "export_tables": true, "consolidate_tables": true},
    {"id": "B", "name": "Transform", "x": 374, "y": 223,
     "rows": [{"source_kind": "file", "file": "C:/SAS/transform.sas", "mode": "lines", "row_start": 10, "row_end": null}]},
    {"id": "C", "name": "Report", "x": 748, "y": 0,
     "rows": [{"source_kind": "file", "file": "C:/SAS/report.sas", "mode": "whole"}]}
  ],
  "edges": [{"from": "A", "to": "B"}, {"from": "A", "to": "C"}, {"from": "B", "to": "C"}]
}
```

Replace every example path and section with real ones. Files must be inside the
app workspace or a folder configured under Settings → Folders. Use forward slashes
in Windows paths, as above, or escape each backslash as `\\`. An EGP can be omitted
while designing; choose an automatic/browsed connection before execution.

## Meaning of the fields

| Field | Meaning and default |
| --- | --- |
| `format` | Exactly `pysas-task-graph-authoring-1` for AI/human-written plans. |
| `name` | Graph name, up to 120 characters. |
| `workers` | Maximum simultaneously running tasks: integer 1–32, default 10. |
| `egp` | Optional local connection EGP path. All tasks use this connection. |
| `server_program` | Optional uniquely named code node used to choose a server in a multi-server EGP. Its original code is not automatically run. |
| `shared_work` | Optional `enabled`, `path`, `libref`. On execution PySAS uses the current Settings path/libref and retains the checkbox choice. |
| `setup` | Ordered shared setup cards; their source rows are prepended before **every** task. They are never separate jobs or dependency endpoints. |
| `nodes` | List of tasks. Each task is one independent SAS submission/session. |
| `edges` | `{ "from": "prerequisite ID", "to": "dependent ID" }`. A→B means B waits for A to succeed. |
| `viewport` | Optional canvas `{ "x": 50, "y": 210, "zoom": 1 }`; zoom .25–2. |

Each task/setup card needs a unique `id` (1–64 letters, digits, underscores or
hyphens; unique ignoring case), a `name`, and ordered `rows`. Task `x` and `y`
positions are optional in authoring JSON, within ±100,000. Use Arrange after import
to lay out dependencies. Optional per-task output flags are `export_html` (default
true), `export_tables` (false) and `consolidate_tables` (false).

Each source row uses one of these authoring choices:

- `source_kind: "file"`, plus `file: "C:/path/program.sas"`.
- `source_kind: "inline"`, plus `name` and SAS `code` as a JSON string. Escape
  newlines as `\n`, double quotes as `\"`, and backslashes as `\\`.

Source-row IDs are optional in this format; PySAS generates them. Files are read,
hashed and scanned locally during import. The AI does **not** need file hashes or
base64 assets. Missing/disallowed paths cause a clear import error: correct the
paths or configure the input folder, then restore again. Import never starts SAS.
Embedded EGP program selection is available in the editor; use the editor to add
those sources and export a portable template instead of inventing program IDs.

## Selecting source

- `mode: "whole"`: entire file/code (the default).
- `mode: "lines"`: `row_start`/`row_end`, positive integers, 1-based, inclusive.
  One can be `null` for start/end of file. Both blank is invalid; use `whole`.
- `mode: "section"`: `sections: ["Name", "Another"]`, nonempty and unique.
  The UI selects existing sections in source order. Authoring JSON preserves the
  array order, so list them in the intended submission order. Markers must be:

```sas
* (please do not delete) section_start: Realised;
/* SAS statements to submit */
* (please do not delete) section_end: Realised;
```

Names are compared ignoring case; each matching pair must be unique, ordered and
contain code. Keep marker lines complete and separate. The submitted code excludes
the marker lines. Source cards expose detected sections, Refresh source and line
range validation using the same parser as Run stream.

## Execution semantics

Run graph submits ready tasks up to the worker limit. All direct prerequisites
must finish successfully; a failed/cancelled prerequisite blocks descendants,
including indirect descendants. Independent branches can finish. A full-graph
stop cancels active automation and prevents new tasks from starting. Stop file
affects that task and therefore blocks its dependents.

The effective code for each task is: current shared WORK assignment if enabled →
all setup cards and their rows, in list order → that task's own rows, in list order.
Each task uses `engine.py` just like Run stream, with its own log, HTML/table
choices and frozen inputs. Rows in one task share one SAS session; separate tasks
do not share WORK/macro variables by default. Dependency arrows order execution;
use permanent libraries or shared WORK to pass tables between tasks. Include
macro definitions in shared setup when every task needs them.

Run this task only is manual mode: it includes shared setup but does **not** run
prerequisites. Choose it only when those inputs already exist or are unnecessary.
Runs open Overview immediately during preparation. Inspect the whole run and
individual tasks for elapsed time, source, logs, results, Copy/Download and ZIP.
The parent `run.log` consolidates task logs. Run again creates a fresh run from
saved choices and current linked sources. This version does not resume graph
attempts; Excel schedule continuation remains separate.

## Editor/export format and portability

The app saves/exports `pysas-task-graph-1`. It has the same graph structure, plus
source-row/program IDs and file references `{ "path": "...", "name": "program.sas",
"sha256": "64 lowercase hexadecimal characters", "origin_path": "optional original path" }`.
Connection/source EGP references have the same shape. EGP rows contain `project`
and ordered `programs` with `program_id`, `id`, `name`, `flow`, `file` and scope.
Do not invent hashes: preserve app-exported references or use the authoring format.

Export JSON embeds original source/EGP bytes under `assets`, keyed by SHA-256 with
base64 values, for restoration on another installation. Keep that exported JSON
unchanged when only analyzing its contents. To edit structure, retain the original
IDs/references/assets, or generate an authoring plan with accessible local paths.
Imports get a fresh graph ID; restoring a file does not overwrite another saved
graph automatically. Normal Save protects against another window's newer edits.

Limits: 200 tasks, 100 shared setup cards, 2,000 dependency edges, 1,000 submitted
source programs and 16 MB inline code. Files: 16 MB per SAS source, 64 MB per EGP;
the combined source/asset limits from Run stream also apply. Graph JSON can be
up to 128 MB with embedded assets; saved editable definitions up to 20 MB.

## Suggested prompt for your AI

> Create valid `pysas-task-graph-authoring-1` JSON using this manual. Use my real
> paths and section names. Put common libraries/macros in ordered setup cards.
> Give every task a unique ID, and encode prerequisites as from→to edges without
> cycles. Do not invent SAS code, paths or section names I have not supplied.
> List any missing information separately. Return the complete JSON file.
