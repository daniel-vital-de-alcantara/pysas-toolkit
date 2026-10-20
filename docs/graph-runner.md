# Graph runner · testing preview

The **Graph** tab is a separate way to prepare a single program or a dependency schedule. The existing **Run** tab and Excel schedule commands remain available. Included in Workbench 0.4.0-preview.32 with standalone engine 0.3.16.

## Build a graph

1. Open **Graph** (Alt, G), give the graph a name, and expand **Add programs**.
2. Link `.sas` files by their path on this computer, or upload SAS files or an EGP. For an EGP, browse its embedded programs and choose which ones to add. Linking SAS files reads the current source when a new run starts; uploading makes a separate local copy.
3. Add library or macro programs to **Shared setup**. The up/down buttons control their order. **Add _*.sas from Settings** brings in the configured initialization files. Shared setup is prepended into every program's submission in that order; it never occupies a separate execution slot. It executes on each target program's server.
4. Select a program, click **Link selected →**, then select the program that must wait for it. An arrow **A → B** means B depends on A. Independent programs can run together. The default is 10 parallel programs.
5. Select a card to edit its display name, source, section, inclusive row range, skip rule, error handling or table export. Click **Apply program changes**. Use a section or rows, or leave both blank to submit the whole file. Sections use the existing terminal markers (`* (please do not delete) section_start: Name;` and the matching `section_end`).
6. Use **Check graph**, **Save graph**, and **Run graph**. A single card is a single-file run. Saving and checking are available on macOS; SAS execution requires Windows and Enterprise Guide.

For linked SAS files, choose a connection EGP, upload one, or use the default connection from Settings. As in the standalone file runner, the first code object in that EGP supplies the SAS server connection. Embedded EGP programs retain the selected program's own server connection. Programs whose source is external to the EGP must be linked as actual SAS files instead. Duplicate program names within an EGP must be renamed in Enterprise Guide before they can run through Graph; this prevents selecting the wrong server by name.

Circular links, missing dependencies and conflicting row/section selections are rejected. Shared setup cannot have dependency arrows. A skipped card remains a barrier: **A → skipped B → C** still makes C wait for A. If A fails, skipping B cannot release C. “Stop graph after an error” follows the existing schedule rules: pending work stops; work already submitted continues unless the graph is stopped explicitly. A shared setup definition with this option applies the rule to every target.

## Canvas and keyboard

- Drag cards to arrange them; drag empty canvas to pan. Zoom and Arrange are above the canvas. Select an arrow to remove it, or remove a prerequisite from the program editor.
- Alt, G opens Graph. Alt, X shows page commands; C enters the canvas. Arrow keys browse cards, Enter opens the selected card's editor, and Ctrl + arrows moves it. Shift makes movement larger.
- To link with the keyboard, select the prerequisite, activate **Link selected →**, return to the canvas, use arrows to choose the dependent program and press Enter.
- Delete removes a selected card and its links. Ctrl + Z / Ctrl + Shift + Z undo and redo graph edits. Ctrl + S saves the graph. Native text-field undo is preserved.

## Execution, stopping and continuation

Graphs use the same scheduler queue, worker process, Windows console setup, cancellation controls, elapsed-time accounting, logs and inspectors as Excel schedules. They do not introduce a second scheduler engine. Excel is not required for graph execution; without `openpyxl`, CSV/text summaries and the consolidated SAS log remain available.

Each new run freezes the graph, original source bytes, selected source and EGP connection templates before it submits any SAS work. Changes to linked files or to the editor affect the **next new run**. Missing or invalid source causes preparation to fail before SAS starts. Sources are checked even for skipped cards so that the saved graph is complete.

Use **Stop graph** to cancel the full schedule and prevent pending cards from launching. Individual running files can also be stopped in the existing inspector. **Continue saved run** retries unfinished programs from the frozen source, retains successful outputs, consolidates the schedule log and continues the active elapsed time without counting the pause. Changed/missing execution snapshots are rejected instead of silently submitting altered code. Draft edits do not alter continuation.

Saved run folders live under the configured `tasks/schedules` folder. They contain `graph.json`, `graph-sources.json`, `sources/`, per-task `_submitted.sas` files, logs, results and normal schedule summaries. `graph-sources.json` records the original source locations and SHA-256 hashes of full source, selected source and connection assets. Saved graph files live in `settings/graphs`; uploads live in `tasks/graph-sources`. The existing Tasks list and inspectors provide logs, download, original-file copy and ZIP export.

## JSON and moving computers

Save/Open keeps graph documents locally. Export/Import JSON transfers graph definitions; importing creates a new graph ID. Export does not include source files. Saved graph JSON also has the regular Download and Copy file actions. Revision checks prevent a stale window from overwriting another window's saved graph.

The full saved-data backup includes saved graphs, uploaded graph sources and frozen run folders. Configs-only includes graph definitions but excludes source uploads and run evidence. Restore preserves both versions of colliding graphs/uploads and updates their references. Linked files outside the app need separate copying or relinking. Portable Tasks/Settings folder locations work for graphs too.

The standalone single-file engine supports the same JSON format:

```console
python pysas.py graph run plan.json --workers 10
python pysas.py graph continue path/to/saved-graph-run
```

A minimal document is:

```json
{
  "format": "pysas-graph-1",
  "id": "daily_extract",
  "name": "Daily extract",
  "connection": "connection.egp",
  "workers": 10,
  "setup": [
    {"id": "libs", "name": "Libraries", "source": {"type": "file", "path": "_libs.sas"}, "x": 0, "y": 0}
  ],
  "nodes": [
    {"id": "extract", "name": "Extract", "source": {"type": "file", "path": "extract.sas"}, "x": 60, "y": 60},
    {"id": "report", "name": "Report", "source": {"type": "file", "path": "report.sas"}, "x": 370, "y": 60}
  ],
  "edges": [{"from": "extract", "to": "report"}]
}
```

An embedded source uses `{"type":"egp","path":"project.egp","program_id":"CodeTask-..."}`. Source paths in standalone JSON are relative to the JSON file. UI uploads use portable `tasks/graph-sources/...` paths, which the app resolves before launch. Optional program fields are `section`, `row_start`, `row_end`, `skip`, `stop_process_on_error` (default true), `stop_program_on_error` and `tables`. IDs are unique across setup and nodes, including case; links use exact IDs. Limits: 200 program cards, 100 setup definitions, 2,000 links, 32 parallel programs, 16 MB per SAS source and 512 MB per connection EGP.

## Later: changed-source comparisons

The source snapshots and hashes provide evidence for comparing a later run against an earlier one. This preview runs every enabled program. It does **not** automatically rerun only changed programs or affected descendants. Unchanged code can still produce different results when source tables, macros, parameters, server configuration or external data change; a later incremental-run feature must account for those inputs.

## Verification limits

Automated checks cover graph validation, dependency ordering across skips, shared setup composition, EGP selection/server preservation, source snapshots, stop propagation, continuation, observation events, HTTP routes, backups, editor helpers and legacy workflow regressions. Actual Windows Enterprise Guide/SAS execution and visual desktop acceptance of this new tab still need a live check. The development Mac was locked during visual verification.
