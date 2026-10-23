# PySAS Workbench 0.4.0-preview.37

Graph is now a canvas-first task planner inspired by Control Tree. Define tasks with the source choices you know from Run stream, arrange them, link dependencies and export the complete plan to JSON.

Download **PySAS-Workbench-Python-0.4.0-preview.37.zip**, extract the whole ZIP and open **START_PYSAS.bat**. Python 3.10+ is required. Existing Run stream/runner execution still requires your Windows Enterprise Guide/SAS setup. The single-file CLI remains **pysas.py 0.3.18**.

## Graph editor

- **Canvas fills the window beside the left navigation.** Floating controls and a details drawer leave the workspace available for the graph. Pan, zoom, Fit and Arrange help navigate larger plans.
- **Tasks are Run stream-style definitions.** Each node holds one or more ordered source cards: PC SAS files, inline SAS, or selected EGP programs. Whole files, inclusive ranges and multiple named sections are available. Each source shows its loading/definition status.
- **Drag and connect tasks.** Drag nodes into place; draw a link from a prerequisite's right-hand port to its dependent task. Click-to-link, a Link command and a prerequisite picker provide alternatives. Cycles, self-links and duplicate links are rejected.
- **Special shared setup cards.** The top strip defines libraries, macros or parameters intended to be prepended before every task. Its order is separate from dependencies; reorder by dragging or Move earlier/later. Setup definitions are not separate jobs.
- **Save and portable JSON.** File → Save graph stores a local draft. Export JSON includes source snapshots, inline code, task/setup order, dependencies, positions, viewport, connection and output choices. Download and Windows actual-file Copy are offered. Restore preserves choices on another installation and protects edits made while loading.
- **Keyboard and editing.** Arrows browse tasks, Enter edits, Ctrl + arrows moves, Delete removes and Ctrl + Z / Ctrl + Shift + Z undo/redo graph changes. Ctrl + S saves. Duplicate retains sources with fresh IDs. Native text editing preserves its own undo.
- **Background preparation.** EGP inspection, program extraction and inline analysis leave other tasks editable. Results stay with their task when selection changes and cannot recreate a deleted task. Normal polling preserves the editor cursor.
- **Earlier data remains available.** Legacy graph files open as new task-plan drafts, preserving the originals; unavailable source paths prompt for browsing. Full/config-only backups understand the new definitions and remap colliding saved sources safely.

This is intentionally an **editor preview**. There is no Run graph action and these operations do not start SAS. Tasks use the Run stream source schema in preparation for connecting the new engine later. Existing Run stream, Run, watcher, Excel scheduler and terminal graph execution paths remain available.

## Try it

Create two tasks, add inline or file sources, close the drawer and drag the first task's right port onto the second. Add a shared setup card, review its source order, then use File → Export JSON. Restore the JSON and verify the nodes, definitions, arrows and view. Output/connection/parallel choices are saved for later execution.

Extract into a fresh folder. Close the prior app before pointing Settings → Storage and cleanup to your existing Tasks and Settings folders, then restart. Keep the previous installation and saved data.

Automated checks cover real editor DOM events, pointer/keyboard links, camera transforms, undo/redo, asynchronous source isolation, source composition/encoding, portable/legacy restoration, revision checks, HTTP routes, backups and the existing execution workflows. The Windows/macOS/Linux release checks gate publication. Desktop visual acceptance of the redesigned canvas remains pending in the target environment; the development Mac was locked.

Read the [task graph guide](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.37/docs/graph-runner.md) and [Run stream guide](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.37/docs/run-stream.md), both included in the ZIP.
