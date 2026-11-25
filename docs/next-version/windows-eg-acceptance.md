# Manual Windows / Enterprise Guide acceptance

Status: target-environment checks pending. The user authorized publishing testing previews for testing with Graph, portable data and Settings keyboard improvements. These manual checks still remain; draft PRs stay unmerged. Automated Windows COM tests use fake EG objects, not a production SAS server.

## UI and keyboard

- Capture Overview, Single file, New/Continue schedule, Projects, Tasks inspector (Outputs/Logs/Tasks), Settings, Servers/Columns, sample results and dictionary screenshots.
- Check 100%, 150% and 200% Windows scaling and narrow windows. Inspect Back/Escape, focus return, list scroll, Alt/F10 hints and arrow-key lists. Navigation: O Overview, R Run, G Graph, P Projects, V Servers, S Settings.
- Confirm elapsed seconds advance smoothly during a large log preview, slow storage scan, ZIP compression and metadata refresh. Verify header elapsed/finish labels and historical pause-adjusted continuation time.

- Settings: Alt, S shows eight section hints. B opens Backups with local action hints; Escape returns to sections, then navigation. Check off-screen sections, long pages, file pickers, disabled actions and repeated opening.
- Graph: import SAS/EGP sources; link cards by pointer and keyboard; shared setup order; validation, save/reload, undo/redo and narrow/high-DPI canvas layout.

## Existing execution and storage

- Run a single file with shared-folder and inbox `_*.sas` files, with parameters on/off and an initialization override. Compare the Run preview, Console file order and exported code: initialization → parameters → target. Confirm inbox jobs are not moved or queued.
- Single-file plan: choose default/shared/override initialization; check full paths and order before submission. With a saved default override, Shared must still use the automatic list. Refresh inventory while an override is selected; it must remain selected. Change/delete a file after preview; submission must stop for an updated review or fail before EG, without silently falling back.
- Inspect `run.log` after success, SAS error and cancellation: ordered paths, snapshots/hashes, preparation, complete SAS log and automation output. Check numeric `PYSAS_FILE_START|N` / `PYSAS_FILE_END|N` markers with NOSOURCE/NONOTES as well. An early SAS abort must not be described as successful execution of later files. Verify Copy/Download and ZIP include all evidence.
- Compare a normal program and representative schedule against the known working terminal engine: three always-run definitions prepended to each task, sections/rows, default ten workers, skipped intermediate dependencies, stop-on-error and global/per-file stop.
- Continue an interrupted schedule. Confirm no successful task is rerun; original start remains, active elapsed excludes the pause, latest activity moves the run up, final task folders and consolidated schedule.log retain correct attempts.
- Start watcher explicitly, then test opt-in startup and restore (must disable startup). Confirm initialization/shared WORK behavior is unchanged for runner, watcher and scheduler.
- Test default/ambiguous EGP selection; missing external folders; parameters; app restart; config-only and full backup restore on a second workspace/PC. Confirm names and recents survive without starting jobs.
- Test Pack/Unpack with spaces/network paths, corrupted bundles, overwrite confirmation, backups and counts; unchanged destination after failed verification; files absent from a bundle retained. Verify Download/Copy file and Explorer on the correct artifact.
- Export a completed run while starting an unrelated command. Confirm that command starts, is excluded from the prepared backup, and the exported schedule cannot be continued until its ZIP is ready.

## Metadata and bounded data reads

- Test library discovery with initialization on/off; verify the off case submits no `_*.sas` or shared WORK assignments. Confirm the selected EGP chooses the intended server and a new session is used.
- Refresh sibling libraries/tables concurrently. Deny one table and one library: keep readable siblings, unreadable member names, unknown sizes/counts, warnings and independent timestamps. Test an unavailable column schema and UTF-8/ANSI/UTF-16 log exports.
- Preview empty, numeric, character, date/formatted, missing-value and Unicode data. Compare AND/OR, equality/range, contains/starts and missing filters against a manual read-only query. Quotes, percent/ampersand and unusual names must remain data/identifiers.
- Verify 100 default / 1,000 maximum rows, 100-column cap, long-cell flags, transport budget, unordered sampling notice, source unchanged, exported sample parity and per-file cancellation. Check permission/connection failures are reported without stale result substitution.
- Collect multiple libraries' missing columns. Confirm serial progress, sibling retention, stop-after-current, failed-table continuation and batch/column caps. Search across tables; compare CSV/XLSX exports with displayed filters and explicit missing/stale rows.
- Confirm returned table samples are stored locally in artifacts/run logs and backups as described; use only data appropriate for the local computer.

## EGP extraction acceptance

- Extract a representative real project. Compare program labels, classic/newer flow membership and source bytes with the original/MagicRoot output. Verify duplicate names, linked-program warnings and full-folder ZIP.
- Edit one flat file, then a grouped copy, and repack into a new EGP. Open it in Enterprise Guide, confirm only intended source edits and other project elements preserved. Conflicting edits must be reported before any output is published.

## Legacy CLI graph execution acceptance

- Compare a linked SAS node and an embedded EGP node with their existing Run/terminal executions. Confirm each uses the intended server, selected section/rows and ordered shared setup.
- Test a parallel graph, default 10 workers, skipped intermediate dependencies, per-file stop and Stop graph. Continue after an error using frozen source and retained successful outputs.
- Modify a linked file after a run starts. Confirm the active run and continuation retain snapshots, while a new run uses the edited file.
- Export/restore full saved data with uploaded graph sources, colliding names and configured external Tasks/Settings folders. Confirm graphs and continuation keep the correct associations.

## Task graph editor acceptance (preview.37)

- Confirm the canvas fills the window beside the navigation at 100%, 150% and 200% scaling and in narrow windows. Add tasks, open/close the drawer, select another card while editing, pan, zoom around the pointer, Fit and Arrange. Source editors must follow the selected task without losing other definitions.
- Mix inline code, files, named sections/ranges and ordered EGP programs in one task. Keep editing a second task while extraction finishes on the first; delete a loading task and undo/redo edits. No editor action may start SAS or submit a legacy scheduler command.
- Link by dragging ports, click-to-link, the toolbar and the prerequisite picker. Use keyboard browsing/linking/movement, remove links and reject duplicate, circular, self and setup dependencies.
- Reorder shared setup cards by dragging and buttons. Export/restore on a second installation: sources, setup order, outputs, connection choice, dependencies, positions and viewport must survive. Test concurrent edits during import/export and saved-file revision conflicts. Legacy documents must open as new drafts without replacing the originals.

## Run stream acceptance

- Start New run with a saved valid EGP and with none available. Check collapsed automatic connection options versus the expanded EGP request. Browse another project while automatic discovery is pending; the manual choice must remain selected. Reading metadata must not start SAS.
- Mix a PC SAS file, inline macro definitions and several programs from an EGP's process flows. Check section tick lists, one-ended inclusive ranges, no-section instructions, blank/invalid selections and ready indicators. Review Get source for the exact chosen order and contents before execution.
- Drag and use keyboard move buttons while programs are extracting. Edit a different card, delete a loading card and switch source types; the UI must remain editable and late results must not replace newer choices. Check narrow/high-DPI layout and focus/cursor preservation.
- Enable shared WORK with a live owning session. Confirm the generated libname/USER setup precedes every selected card and that turning the checkbox off removes it. Run the mixed source once; verify intended server, macros, returned log, HTML/tables and the existing inspector/stop behavior.
- Export/restore both older and current templates on another installation. Check original source encodings, nested EGP program order, inline code, selected sections, shared WORK and output options. Edit during template import; the imported draft must wait for Use imported template instead of replacing those edits.

## Workflow polish acceptance (preview.38)

- Start Run, schedule, Continue and Run stream with large or slow sources. Overview must appear immediately with one Preparing run entry, progressing to the same submission without opening Inspect. Cancel during preparation and during worker startup; confirm no unrequested SAS execution continues. Fail preparation and inspect the finished error/console.
- Pack two versions of one folder, unpack an earlier bundle, and inspect every dated artifact. Copy latest must copy the correct immutable bundle. Rename the folder display label and use Update bundle with remembered pack options. Verify Alt hints and arrow navigation across the three actions and version rows; unpack confirmation/backups remain.
- Link SAS from the workspace and from an external configured input folder. Modify it outside the app and check automatic Last update, changed sections, invalidated ranges and source exports. Update the shared WORK path in Settings. Run again must submit current source and WORK while an earlier run retains its frozen source. Uploaded copies should not claim a live original link.
- Edit while a refresh is pending; source choices, typed code and cursor must remain. Refresh without changes must keep generated download/copy links. Remove a linked file: display a local failure and retry successfully after replacement. Restore portable JSON on another PC without the original paths and run from embedded copies.
- Inspect a failed schedule: Continue must use its existing folder, workers and pause-adjusted elapsed time; Run again must create a fresh schedule. Test a completed stream and an older saved run. Full backup restore in a different workspace must preserve replay configuration and project names.
- Give two completed runs the same exact name. Overview history should group them, while simultaneous active runs remain separate in Running now. Choose an older inspector version, poll/complete another run and switch versions rapidly; selection must stay correct.

## Connected task graph acceptance (preview.40)

- Compare one graph task against the same Run stream: identical ordered setup, source selections, EGP/server, shared WORK, returned logs, HTML/tables and elapsed time. Test a manual task with prerequisites omitted; the UI/log must identify that mode.
- Build A→B→C plus A→C, then Arrange and move B manually. The A→C link must stay visible around B. Check branches/joins, multiple spanning links, 100%/150%/200% scaling and narrow windows. Shift/Ctrl-select tasks, align every direction, distribute, drag/move the group and undo once.
- Run a parallel graph with a small worker limit. Confirm B/C wait for their prerequisites, shared setup is prepended inside each task, failure/cancel blocks descendants, independent branches finish and global Stop launches no further tasks. Compare all consolidated/task logs and output folders; inspect and copy/download/ZIP each scope.
- Change a linked SAS file and shared WORK location before Run, then change the original during execution. The new run must use the refreshed source/WORK and preserve its frozen snapshot after launch. Restore file/inline/EGP section selections and use Refresh source/sections. Check UTF-8/UTF-16/Windows-1252 with canonical paired markers.
- Download the JSON manual from both locations. Restore its authoring format using actual local paths, sections and inline setup; check automatic hashes and source metadata without starting SAS. Missing paths, malformed JSON, cycles and duplicate IDs must fail clearly.
- Backup/restore saved graphs and graph runs into an installation with colliding graph IDs. Run again must retain the imported graph association, input paths and manual/full mode. A crashed worker must finish visibly as Failed and retain console evidence. No graph run should appear in Excel schedule continuation.
