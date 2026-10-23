# Task graph · editor preview

The Graph tab is a canvas for designing tasks and dependencies. In Workbench **0.4.0-preview.37**, it replaces the old program-row editor with task definitions based on Run stream. This preview focuses on editing: it has no Run graph control and does not submit, schedule or stop SAS work. The later execution unit will be one combined Run stream-style submission per task.

## Canvas and task cards

Open **Graph** (Alt, G). The canvas fills the window beside the left navigation. Floating controls leave the workspace visible; a details drawer opens only when you edit a task or graph settings. The layout follows the canvas-first approach of Control Tree while retaining PySAS's blue accent and existing app shell.

- **＋ Task** creates a node and opens its definition. Give it a name, then add one or more source cards. A task is an ordered mini-stream, not a separate node for every source selection.
- A source card can browse a **SAS file**, **Write code** directly, or select ordered **EGP programs** by process flow. Whole files, inclusive line ranges and multiple named sections use the same choices and marker syntax as Run stream. Library files, inline macro variables and target code can share a task.
- File/EGP reads and inline section analysis show local loading indicators. Other task definitions stay editable while work completes, including after you select a different node. Defined/incomplete indicators identify missing inputs. Incomplete drafts can still be saved.
- Drag a node to position it. Click another task while the drawer is open to switch its definition. **Edit task** or Enter opens the drawer; Close returns to the canvas. Duplicate retains source choices with fresh IDs; Delete also removes that task's arrows. Undo can restore deleted cards.
- Use **＋ Shared setup** for special cards in the strip above the task area. Their sources are intended to be prepended before **every task**, in strip order, inside that task's submission. They are definitions, not independent jobs, and never have dependency arrows. Drag them to reorder or use Move earlier/later in their drawer. The strip can collapse when you need more room.

Within a task or shared setup card, **Add file or code** stays below the last source. Use source grips or up/down buttons to order files; selected EGP program subrows have their own ordering controls. External EGP code is identified without fetching its original path; browse that SAS file instead. Existing source encodings are preserved in the snapshots and JSON.

## Dependencies

An arrow **A → B** means B depends on A. Each task may have several prerequisites or dependents, so the plan supports a dependency graph rather than only a strict tree.

Create an arrow in any of these ways:

1. Drag A's right-hand connection port onto B.
2. Click A's right-hand port, then click B or its left-hand input.
3. Select A, choose **Link →**, then choose B.
4. Open B's drawer and add A under **Wait for task**.

Circular dependencies, duplicate links, self-links and links to shared setup are rejected. Click an arrow to remove it in the dependency drawer, or remove a prerequisite from a task's list. **Check graph** checks the structure and reports cards that still need source definitions. It never starts SAS.

## View and keyboard

- Drag empty canvas to pan; normal wheel movement also pans. Ctrl + wheel zooms around the pointer. Use the bottom − / percentage / ＋ controls to zoom, **Fit** to bring tasks into view, or **Arrange** to place prerequisites in earlier columns.
- Arrow keys browse nearby tasks. Enter edits the selected task. Ctrl + arrows moves it; Shift makes the step larger. Delete removes the selected card or dependency. Escape cancels linking or closes details.
- To link with the keyboard: select the prerequisite, activate Link, return to the canvas, use arrows to choose the dependent task, then Enter.
- Ctrl + S saves; Ctrl + Z / Ctrl + Shift + Z undo/redo graph edits outside text fields. Native text editing keeps its own undo. Alt page-command hints include C Canvas, T Task, B shared setup, L Link, F Fit and A Arrange.

## Connection and future execution options

Click the graph name to open settings. Automatic EGP selection uses the existing background project reader. If no usable project exists, keep designing and browse one later. This reads project metadata without opening Enterprise Guide or checking SAS authentication.

The plan remembers the connection EGP, optional server code-node name, default ten parallel tasks, shared-WORK choice and each task's HTML/table/workbook output options. These describe the future execution plan; this release does not apply those settings to SAS. Shared setup order and dependencies are represented explicitly so that they can be passed to the new engine later.

The standalone `pysas.py` CLI, existing Run/Excel scheduler, watcher and Run stream retain their execution paths. This new task-plan format is separate from the legacy CLI graph format; do not pass a new task plan to `pysas.py graph run`.

## Save and portable JSON

Open **File** beside the graph name:

- **Save graph** keeps the document in `settings/graphs` on this computer. Open a saved graph from the same menu. Revision checks prevent a stale window from overwriting a newer saved version.
- **Export JSON** prepares a portable `.graph.json` with the graph name, task/setup definitions, ordered sources, connections, dependencies, positions, viewport/zoom and future output options. SAS/EGP files are embedded once by checksum, including extracted program bytes. The result offers Download and Windows actual-file Copy.
- **Restore JSON** validates before replacing the draft and gives the imported plan a new ID. If you make edits while a restore is loading, **Use imported graph** lets you apply it explicitly. Export results prepared from an older draft are not advertised as the current plan.

Current plans use `pysas-task-graph-1`. Earlier `pysas-graph-1` files can be opened/imported as new task-plan drafts; original saved graph files are preserved. Available sources are mapped to new cards. Missing/unavailable sources retain their previous paths and ask you to browse them again. Review the converted definitions: legacy scheduler skip/error policies are not controls of this editor preview.

JSON may contain private SAS source and EGP connection information, just like the input files. Exporting source snapshots makes the graph portable; it does not include external SAS server datasets or a running shared-WORK session.

Full saved-data backups include task plans and uploaded source snapshots. Configs-only includes definitions and inline code; uploaded SAS/EGP assets require the full backup or portable graph JSON. Restoring colliding graph IDs/source filenames preserves both and remaps their paths. Existing Tasks and Settings folders remain configurable across installations.

Limits: 200 task nodes, 100 shared setup cards, 2,000 dependency links and 1,000 source programs in total. Inline editors accept 1 MB each/16 MB total; distinct SAS assets up to 16 MB, each EGP up to 64 MB, combined assets up to 80 MB. Saved definitions are limited to 20 MB; portable JSON to 128 MB.

## Legacy CLI graphs

Existing terminal graph schedules still use `pysas-graph-1`:

```console
python pysas.py graph run legacy-plan.json --workers 10
python pysas.py graph continue path/to/saved-graph-run
```

Their source snapshots, shared setup, dependency scheduling, stop and continuation behavior have not been connected to or replaced by this editor. Earlier saved runs remain inspectable through Overview.

## Verification

Automated tests cover actual task-editor DOM events, mouse/keyboard linking, dragging/panning/zoom, cycle rejection, setup ordering, source editing, asynchronous result isolation, undo/redo, source encodings, portable/legacy import, revision protection, HTTP routes, backups and packaged assets. Tests explicitly reject execution side effects from editor operations. Windows/macOS/Linux release checks also retain the existing execution regressions. Desktop visual acceptance remains pending in the target environment; the development Mac was locked during this work.
