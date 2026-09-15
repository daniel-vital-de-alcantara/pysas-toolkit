# Execution investigation: 0.3.2 versus Workbench

The reported last line is `Running: ..._PySAS`. In the current bridge this is immediately before the synchronous `code.Run` call. The following line is emitted only after that call returns. This locates the reported wait inside Enterprise Guide/SAS execution, before log export and project shutdown. It does not identify the server-side reason. No actual SAS server is available in the development/test environment.

## Verified differences

| Area | Published 0.3.2 | Workbench before preview.13 | Action |
| --- | --- | --- | --- |
| Scheduler concurrency | Without --workers, derives limit from workbook max_parallel | UI forces --workers 2 | UI now defaults to 0: omit override and use workbook |
| always_run | Rows are separate scheduled tasks; not prepended | Enabled rows are prepended to each normal task; not separately scheduled | Preserve current shared-setup behavior, but provide original engine comparison |
| Submitted program | Requested program slice | All enabled setup slices, then requested program slice | Current console lists each prepended slice and saved submitted-code path |
| UI event/output transport | No UI reader | Worker writes both to a pipe; UI reader saves history synchronously | Separate append-only events and direct console files; SAS does not depend on UI draining output |
| Observer failure | No UI observer | History write exception can terminate reader and leave worker blocked on output | Keep observing on history-write errors and finalize in-memory completion |
| Automation launch | cscript inherits terminal context; subprocess.run captures output | cscript uses CREATE_NO_WINDOW; parent worker also hidden | Difference remains explicit; no evidence yet that window context causes this wait |
| COM submission | Create EG application, open project, add code item, set options, code.Run | Same synchronous lifecycle, but different submitted setup text | Original comparison uses unchanged bridge; no COM live-log polling |

The user reports three enabled always_run rows. Their actual code and ranges have not been inspected. Repeated setup may be relevant, but duplication, locks, authentication, server availability or any particular SAS statement have not been established as the cause. UI transport fixes are independently reproducible; they do not by themselves explain code.Run waiting.

## Controlled comparison in the app

In Scheduler choose **Original 0.3.2 · terminal comparison** and leave **Maximum parallel tasks** at **0** to honor the workbook. Use the same workbook and EGP as the successful terminal run. The bundled `pysas_0_3_2.py` is the exact source from repository commit `e4604e2` (SHA-256 `27a21be8e39a87823b481e00d8f1e0e4bfba7add9995c9a70ea4310fa668dd33`). It is also runnable directly from a terminal as a single file.

The UI wraps function entry/exit for timing and status. For a custom workspace it sets the engine ROOT_DIR to that workspace. It does not replace the original scheduler, submitted-code builder, execute_eg, or VBS implementation. The original engine's own behavior is preserved: always_run is not shared setup, console capture becomes available after automation exits, and per-file cancellation is unavailable. The UI labels the selected original engine and hides unsupported Stop file buttons.

The comparison is intentionally limited to scheduler/continuation, matching the reported `_PySAS` program. Watcher input-folder and underscore-initialization support stays on the current engine.

A direct terminal comparison uses `python pysas_0_3_2.py schedule --workbook "Schedule.xlsx" --project "Project.egp" --no-notify` from the extracted folder; use the same absolute input paths if files are elsewhere. Both UI and terminal can still wait indefinitely if code.Run does not return. This release does not turn elapsed time into a fake success or impose an arbitrary timeout on long SAS work.

If original 0.3.2 completes inside the UI and current does not, the changed engine/submission is implicated. If both fail inside the UI while the exact bundled original completes in a terminal with the same inputs and concurrency, investigate the remaining process/window environment difference. In current mode, Inspect > Code contains the exact submitted source, saved before code.Run, including prepended setup. It can be compared locally without uploading private SAS code.

## Validation and limits

Regression tests verify the pinned original source, old-versus-current setup ordering, workbook worker defaults, worker completion while the UI lock is held and more than a pipe's capacity of output/events is produced, and completion after history writes fail. Existing cancellation, encoding, launch, scheduler and UI tests remain in place. Windows CI checks Windows integration, but has no licensed Enterprise Guide/SAS server and cannot certify that the reported SAS wait is resolved.
