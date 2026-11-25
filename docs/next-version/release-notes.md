# PySAS Workbench 0.4.0-preview.42

Graphs can now contain other graphs, with navigation and execution through the hierarchy.

Download **PySAS-Workbench-Python-0.4.0-preview.42.zip**, extract it completely and open **START_PYSAS.bat**. Python 3.10+ and your configured Windows Enterprise Guide/SAS environment are required for execution.

## Graph cards

- **＋ Graph** creates a nested graph card. Open it from its drawer, double-click it, or press Enter on the selected card. **Back**, **Alt+Left** and breadcrumbs return to any parent level. Each graph retains its own layout/viewport; Undo/Redo covers the whole document.
- Copy a saved graph or restore graph JSON inside a card. Copies are independent. **File → Save this level as new graph** creates a reusable library copy. **Save full graph / Export JSON** retain the entire orchestration and all nested definitions.
- Graph cards connect to prerequisites/dependents like ordinary cards. Their inner process starts after outer prerequisites succeed; downstream cards wait until every inner card succeeds. Failures/cancellations block dependent branches, including outer dependents. Independent branches may finish.
- Inner tasks inherit the parent connection and shared WORK choice by default; inner settings can override either. Ancestor shared setup is prepended from outermost to innermost before each source task. Graph containers submit no SAS source of their own.
- All inner SAS submissions in one launch share the outer parallel limit (default 10). Inner limits additionally cap their subtree. Containers do not occupy SAS worker slots or create nested worker pools.

## Running and inspecting

- Run the outer graph, a selected set of cards, one graph card, or the graph level currently open. Inner/partial runs retain ancestor setup/settings and list omitted prerequisites in the parent log. Run again remembers the exact scope. Overlap protection covers parent/child scopes.
- Overview shows graph progress and individual task elapsed times. Graph containers have Stop graph controls; source tasks retain Stop file. Stopping a graph card cancels its subtree while independent work continues. Outer Stop stops the whole launch.
- Each graph inspector lists its immediate children, with inspectors below it. Task source/results remain in their own folders. Each graph consolidates descendant logs once, with elapsed time/status; completed inner logs are ready while outer work continues. Root/nested ZIP, Copy and Download use the existing inspector workflow.
- Timing history finds nested source submissions. Remaining-time estimates account for graph gates and both outer/local parallel limits, retaining the unknown/partial-history indicators.

## JSON compatibility and checks

New editor/portable JSON uses **pysas-task-graph-2**; AI authoring uses **pysas-task-graph-authoring-2**. Earlier flat task-graph version 1 files remain importable. Version 2 prevents older previews from silently dropping nested cards. The downloadable JSON manual includes a nested example. Limits are 8 nested levels and 1,000 cards/1,000 source programs across the document; per-level canvas/source limits still apply.

Automated checks cover hierarchy gates, local/global concurrency, setup order, connection overrides, failure/cancellation propagation, selected inner runs, worker handoff/replay, offline inspectors, nested timing reuse/forecasts, source isolation during navigation, whole-document undo, saved copies and portable JSON. Existing Python/JavaScript regressions and Windows/macOS/Linux CI gate publication. Live SAS and visual desktop acceptance remain for the target Windows computer; browser access was unavailable during development.

Extract into a new folder and close the old app before reusing your Tasks/Settings folders. Back up your saved data before opening/saving graphs across app versions.

Read the [Graph guide](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.42/docs/graph-runner.md) and [JSON manual](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.42/docs/graph-json-manual.md), both included in the ZIP.
