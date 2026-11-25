# PySAS Workbench 0.4.0-preview.41

Graph keeps its canvas design and original curved links, with partial graph runs and a Home/View menu hierarchy.

Download **PySAS-Workbench-Python-0.4.0-preview.41.zip**, extract the entire ZIP and open **START_PYSAS.bat**. Python 3.10+ and your configured Windows Enterprise Guide/SAS environment are required for execution.

## Graph selection and partial runs

- Right-click a task for **Run selected**, **Select prerequisites** (immediate upstream), **Select all dependencies** (every upstream level) and **Select all dependents** (every downstream level). Selection actions retain the starting cards. Right-clicking an already selected card preserves the group; another card becomes the sole selection.
- **Run selected** submits exactly those tasks plus shared setup, retaining dependencies within the selection. The menu warns about unselected prerequisites; the parent log lists them as assumed available, not executed. Unselected incomplete cards do not block preparation. Select all dependencies first to include upstream work.
- Selected runs use the existing Run stream engine and appear immediately in Overview as Preparing run. Logs, outputs, elapsed times, stop controls, task inspectors, Copy/Download and ZIP remain available. **Run again** preserves the exact selection. Disjoint selections may run concurrently; overlapping scopes are blocked.
- Shift+F10 / the Context Menu key opens selection actions. Arrow keys, Home/End and Escape navigate the menu. Shift/Ctrl-click and Ctrl+A still support multi-selection.

## Menus, layout and canvas

- **Home → Arrange → Align** contains Auto, alignment and distribution. **Fit** is under Arrange. **Undo/Redo** are under Home. **View** contains Zoom in/out and reset.
- Press/release **Alt**, then **H → G → A** to open Align. Follow with A for Auto or L/C/R/T/M/B for an alignment. **Alt → H → G → F** fits; **Alt → W** opens View. Escape goes back one level.
- Original Bézier curves are restored. **Auto** changes card positions to keep intermediate cards away from spanning links, including A→B→C plus A→C. It makes a bounded best effort for dense graphs. Manual positioning is unrestricted: links may pass underneath cards and are never rerouted around them.
- Clicking empty canvas clears selection/link mode, closes details and dismisses menus. Dragging the background pans while retaining the selection.

## Validation and upgrade

Automated checks cover shipped HTML/JavaScript events, nested Alt menus, context menus, transitive selection, partial-run preparation and worker handoff, internal dependency ordering, omitted prerequisites, conflict guards, replay/backup choices, card placement and fixed curve geometry. The existing Python and JavaScript regressions and Windows/macOS/Linux CI gate publication. Production SAS and visual desktop acceptance remain pending on the target Windows computer; the development Mac was locked and local browser access was unavailable.

Extract into a new folder. Close the old app before pointing Settings → Storage and cleanup at your existing Tasks and Settings folders, then restart. The independent `engine.py`, standalone CLI and existing scheduler/watcher workflows remain available.

Read the [Graph guide](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.41/docs/graph-runner.md) and [Graph JSON manual](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.41/docs/graph-json-manual.md), both included in the ZIP.
