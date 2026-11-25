# PySAS Workbench 0.4.0-preview.40

Graph keeps its canvas design and now runs tasks through the Run stream engine. This preview also adds AI JSON instructions, alignment/distribution and better dependency layout/section refresh.

Download **PySAS-Workbench-Python-0.4.0-preview.40.zip**, extract the entire ZIP and open **START_PYSAS.bat**. Python 3.10+ and your configured Windows Enterprise Guide/SAS environment are required for execution. The independent `engine.py` and standalone `pysas.py 0.3.18` remain available.

## Graph execution

- **Run graph** starts a dependency run through `engine.py`, one combined submission per task. All shared setup source is prepended before every task; it is never a separate job. Parallelism defaults to 10 and can be set from 1–32.
- Dependencies wait for success. Failed/cancelled prerequisites block all descendants; independent branches can finish. Global Stop graph prevents new tasks and cancels active local automation. Per-file stop remains available in Overview/Inspect.
- **Run this task only** in the task drawer includes setup and deliberately omits prerequisite execution. Other cards may remain incomplete for a manual test. Close the drawer for the full Run graph control.
- Launch immediately opens Overview with Preparing run. Sources/current shared WORK are refreshed, and every submission is validated/frozen before SAS starts. The graph and its task folders retain source, logs, HTML/tables, elapsed time, Copy/Download and ZIP. The parent `run.log` consolidates task logs. Node badges show the last submitted task states when returning to the canvas.
- **Run again** creates a fresh graph from saved choices. Graph continuation is not part of this preview; the existing Excel scheduler/legacy CLI continuation is separate. Tasks have separate SAS sessions: use shared WORK/permanent libraries for tables and shared setup for macros needed by every task.

## Canvas and JSON

- **Arrange** reserves bypass lanes for spanning edges. A→C is routed around B when A→B→C is also present. Links avoid intermediate task cards after manual movement too.
- **Align** offers left/right/top/bottom, horizontal/vertical center and even distribution. Shift/Ctrl-click selects multiple tasks; Ctrl+A selects all. Drag/move the group, undo/redo positions, and keep source/dependency definitions intact.
- **Sections** use fresh metadata from the same parser as Run stream. Saved references without analysis load before becoming Defined. Refresh source / sections rereads a file; File → Refresh sources updates all active sources. Link a local file path to follow edits. Inactive source drafts do not block execution.
- **JSON guide for AI** is downloadable in Graph → File and Settings → Defaults. It documents the full schema, dependencies, setup, sections, sessions and limits, with an example and AI prompt. New `pysas-task-graph-authoring-1` import binds local paths and computes hashes automatically. Existing portable templates still embed snapshots and restore offline.

## Validation and upgrade

Automated checks cover actual canvas/source-editor events, multi-selection/alignment/drag/undo, obstacle routing, JSON authoring and HTTP downloads, UTF-16 section parity, real threaded dependency scheduling, failures/cancellation, worker observation, immutable sources, task timing reuse, inspectors and backup identity remapping. Windows/macOS/Linux checks gate publication. Production SAS execution and desktop visual acceptance still need testing on the target Windows computer; local browser access was unavailable and the development Mac was locked.

Extract into a new folder. Close the old app before pointing Settings → Storage and cleanup at your existing Tasks and Settings folders, then restart. Keep the previous installation and a saved-data backup while testing.

Read the [Graph guide](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.40/docs/graph-runner.md) and [Graph JSON manual](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.40/docs/graph-json-manual.md), both included in the ZIP.
