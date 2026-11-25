# Task graph · canvas and execution

The Graph tab keeps the canvas introduced in preview.37. In **0.4.0-preview.39**, Run graph connects its tasks to the same independent `engine.py` submission used by Run stream. Each task composes its ordered sources once, with shared setup first, and waits for its prerequisites. Manual single-task execution is available too.

## Canvas and task cards

Open **Graph** (Alt, G). The canvas fills the window beside the left navigation. Floating controls leave the workspace visible; a details drawer opens only when you edit a task or graph settings. The layout follows the canvas-first approach of Control Tree while retaining PySAS's blue accent and existing app shell.

- **＋ Task** creates a node and opens its definition. Give it a name, then add one or more source cards. A task is an ordered mini-stream, not a separate node for every source selection.
- A source card can browse/upload a **SAS file**, link a known local file path, **Write code** directly, or select ordered **EGP programs** by process flow. Whole files, inclusive line ranges and multiple named sections use the same choices and marker syntax as Run stream. Library files, inline macro variables and target code can share a task.
- File/EGP reads and inline section analysis show local loading indicators. Other task definitions stay editable while work completes, including after you select a different node. Defined/incomplete indicators identify missing inputs. Incomplete drafts can still be saved.
- Drag a node to position it. Click another task while the drawer is open to switch its definition. **Edit task** or Enter opens the drawer; Close returns to the canvas. Duplicate retains source choices with fresh IDs; Delete also removes that task's arrows. Undo can restore deleted cards.
- Use **＋ Shared setup** for special cards in the strip above the task area. Their sources are prepended before **every task**, in strip order, inside that task's submission. They are definitions, not independent jobs, and never have dependency arrows. Drag them to reorder or use Move earlier/later in their drawer. The strip can collapse when you need more room.

Within a task or shared setup card, **Add file or code** stays below the last source. Use source grips or up/down buttons to order files; selected EGP program subrows have their own ordering controls. External EGP code is identified without fetching its original path; browse that SAS file instead. Existing source encodings are preserved in the snapshots and JSON. **Refresh source / sections** rereads a file and revalidates scopes with the Run stream scanner. Restored references without metadata are read before becoming Defined. **File → Refresh sources** updates all active sources. Uploaded files are copies; a linked local path follows edits on the next refresh/run. Inactive card drafts remain available in templates but cannot block execution of the active source type.

## Dependencies

An arrow **A → B** means B depends on A. Each task may have several prerequisites or dependents, so the plan supports a dependency graph rather than only a strict tree.

Create an arrow in any of these ways:

1. Drag A's right-hand connection port onto B.
2. Click A's right-hand port, then click B or its left-hand input.
3. Select A, choose **Link →**, then choose B.
4. Open B's drawer and add A under **Wait for task**.

Circular dependencies, duplicate links, self-links and links to shared setup are rejected. Click an arrow to remove it in the dependency drawer, or remove a prerequisite from a task's list. **Check graph** checks the structure and reports cards that still need source definitions. It never starts SAS.

## View and keyboard

- Drag empty canvas to pan; normal wheel movement also pans. Ctrl + wheel zooms around the pointer. Use the bottom − / percentage / ＋ controls to zoom, **Fit** to bring tasks into view, or **Arrange** to place prerequisites in earlier columns. Spanning edges reserve bypass lanes; card-aware routing takes long links around intermediate nodes, including A→C when A→B→C also exists.
- Arrow keys browse nearby tasks. Enter edits the selected task. Shift/Ctrl-click selects multiple nodes; Ctrl + A on the canvas selects all. Drag a selection together. Ctrl + arrows moves the selection; Shift makes the step larger. Delete removes the selected cards or dependency. The drawer Delete button removes its own card. Escape cancels linking or closes details.
- To link with the keyboard: select the prerequisite, activate Link, return to the canvas, use arrows to choose the dependent task, then Enter.
- Ctrl + S saves; Ctrl + Z / Ctrl + Shift + Z undo/redo graph edits outside text fields. Native text editing keeps its own undo. Alt page-command hints include C Canvas, T Task, B shared setup, L Link, F Fit, A Align, D Arrange and R Run. R runs the selected task while its drawer is open; close it to use Run graph.

## Connection and execution

Click the graph name for settings. Automatic EGP selection uses the existing background project reader. If no usable project exists, keep designing and browse one later. Reading metadata does not start SAS. Graph settings choose the connection, optional uniquely named server code node, maximum parallel tasks (default 10) and shared WORK. Each task has HTML/table/combined-workbook output choices.

**Run graph** moves immediately to Overview with Preparing run. PySAS refreshes known source paths and the current shared WORK path/libref, validates every task, and freezes all task submissions before starting SAS. The code order for each task is current shared WORK (if checked) → shared setup cards/rows in their strip order → that task's own rows. Setup never appears as separate jobs.

Tasks run up to the worker limit after all prerequisites succeed. Failure or cancellation blocks all dependent descendants; independent branches can finish. **Stop graph** prevents new launches and requests cancellation of active owned automation. **Stop file** affects that task; its descendants are blocked. As with Run stream, remote SAS work may outlive local automation cancellation, and returned SAS logs become available when Enterprise Guide returns them.

In a task's drawer, **Run this task only** submits it with setup and omits dependency execution. This mode allows manual testing or repair when prerequisites already exist. It does not claim that other dependencies ran. The other graph cards may remain incomplete for a manual task run.

Each task has a separate SAS session. Arrows order execution; they do not transfer WORK tables or macro variables automatically. Use shared WORK or permanent libraries for tables, and shared setup for macros needed by every task. Rows within one task share one submission/session.

The parent folder is `Tasks/schedules/<timestamp>__graph_<id>/`, with a frozen graph template/plan, `run_summary.csv`, `status.txt`, `graph-result.json` and consolidated `run.log`. Each task folder under `tasks/task_<ID>/` contains its normal Run stream source, original inputs, portable stream template, logs, results and timing metadata. Overview/Inspect, actual-file Copy, downloads and ZIP work for the graph and individual task folders. Successful task timings inform later matching stream/task estimates.

**Run again** starts a new graph from saved choices and fresh linked sources. This version does not resume graph attempts; Excel/legacy schedule continuation stays separate. The existing single-file CLI, Run, watcher and Excel scheduler retain their workflow. Do not pass the new task-plan format to `pysas.py graph run`.

## Align and distribute

Select two or more task cards with Shift/Ctrl-click, or Ctrl + A to select all. Open **Align** beside Fit/Arrange. Align left/right/top/bottom, center horizontally/vertically, or distribute three or more tasks horizontally/vertically. Only selected positions change; source definitions and dependencies stay intact. Each operation and group drag can be undone once. Dependency links are rerouted after positions change.

## Save and portable JSON

Open **File** beside the graph name:

- **Save graph** keeps the document in `settings/graphs` on this computer. Open a saved graph from the same menu. Revision checks prevent a stale window from overwriting a newer saved version.
- **Export JSON** prepares a portable `.graph.json` with the graph name, task/setup definitions, ordered sources, connections, dependencies, positions, viewport/zoom and output options. SAS/EGP files are embedded once by checksum, including extracted program bytes. The result offers Download and Windows actual-file Copy.
- **Restore JSON** validates before replacing the draft and gives the imported plan a new ID. If you make edits while a restore is loading, **Use imported graph** lets you apply it explicitly. Export results prepared from an older draft are not advertised as the current plan.

**JSON guide for AI** downloads the complete [authoring manual](graph-json-manual.md), also linked in Settings → Defaults. An AI can generate `pysas-task-graph-authoring-1` with local file paths or inline code, without inventing SHA-256/base64 data. Restore JSON binds those paths and scans sections locally; import never starts SAS. Current saved/portable plans use `pysas-task-graph-1`. Earlier `pysas-graph-1` files can be opened/imported as new task-plan drafts; original saved graph files are preserved. Available sources are mapped to new cards. Missing/unavailable sources retain their previous paths and ask you to browse them again. Review the converted definitions: legacy scheduler skip/error policies are not controls of the new task runner.

JSON may contain private SAS source and EGP connection information, just like the input files. Exporting source snapshots makes the graph portable; it does not include external SAS server datasets or a running shared-WORK session.

Full saved-data backups include task plans and uploaded source snapshots. Configs-only includes definitions and inline code; uploaded SAS/EGP assets require the full backup or portable graph JSON. Restoring colliding graph IDs/source filenames preserves both and remaps their paths. Existing Tasks and Settings folders remain configurable across installations.

Limits: 200 task nodes, 100 shared setup cards, 2,000 dependency links and 1,000 source programs in total. Inline editors accept 1 MB each/16 MB total; distinct SAS assets up to 16 MB, each EGP up to 64 MB, combined assets up to 80 MB. Saved definitions are limited to 20 MB; portable JSON to 128 MB.

## Legacy CLI graphs

Existing terminal graph schedules still use `pysas-graph-1`:

```console
python pysas.py graph run legacy-plan.json --workers 10
python pysas.py graph continue path/to/saved-graph-run
```

Their source snapshots, shared setup, dependency scheduling, stop and continuation behavior remain in the legacy CLI engine; the new canvas uses Run stream tasks. Earlier saved runs remain inspectable through Overview.

## Verification

Automated tests cover actual task-editor DOM events, mouse/keyboard linking, dragging/panning/zoom, cycle rejection, setup ordering, source editing, asynchronous result isolation, undo/redo, source encodings, portable/legacy import, revision protection, HTTP routes, backups and packaged assets. Tests reject execution side effects from editor operations, and separately verify explicit dependency/manual runs, shared setup, freezing, parallel limits, failure propagation, cancellation, consolidated logs, history, source refresh and matching task timing estimates. Windows/macOS/Linux release checks also retain the existing execution regressions. Desktop visual acceptance remains pending in the target environment; the development Mac was locked during this work.
