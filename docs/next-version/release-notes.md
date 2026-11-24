# PySAS Workbench 0.4.0-preview.38

Launches now appear immediately in Overview, Projects keeps named folder histories, and Run stream follows current linked sources. Inspectors offer Run again/Continue and a dated version picker.

Download **PySAS-Workbench-Python-0.4.0-preview.38.zip**, extract the whole ZIP and open **START_PYSAS.bat**. Python 3.10+ and your existing Windows Enterprise Guide/SAS setup are required for execution. The standalone CLI remains **pysas.py 0.3.18**; `engine.py` and scheduler execution semantics are unchanged.

## Changes

- **Immediate Overview.** Run, schedule, Continue and Run stream show a Preparing run entry before preprocessing. Preparation and execution share the same run ID. Cancellation works before submission and during the handoff; preparation failures finish visibly instead of counting indefinitely. The inspector no longer opens automatically.
- **Separate Pack and Unpack.** Projects has explicit buttons, retaining unpack confirmation and normal source backups.
- **Project folders and versions.** Each folder has a short/default or custom name, last update and three actions: Copy latest file, Update bundle and Inspect. Update reuses its pack options. Inspect lists every saved pack/unpack version, with immutable original bundles available for Download/actual-file Copy. Parallel bundle operations in one folder are prevented.
- **Fresh Run stream inputs.** Linked SAS/EGP paths are checked in the background, with Last update and Refresh sources beside Ready. Run rereads those paths and the current shared WORK location before freezing the submission. Uploaded files remain private copies; use Link local file to follow a known working path inside the workspace/configured input folders. Changed sections/ranges are revalidated; failed refreshes explain the problem locally. Unchanged refreshes keep existing source/JSON links.
- **Run again or Continue.** Finished-run inspectors can launch a fresh run from saved choices. Interrupted schedules can continue in the same folder, retaining successful tasks, consolidated logs and active elapsed time. Older runs without sufficient input metadata prompt for inputs in Run.
- **Grouped history.** Exact same visible names share one Overview Tasks row. Inspect has a dated version selector that stays on your chosen version while the app polls. Every active file remains individually visible and stoppable. Grouping does not merge or delete run folders.
- **Keyboard and portability.** Folder/version lists use Up/Down and Left/Right. Inspector hints include V Versions, R Run again and C Continue. Folder labels and saved launch choices travel with saved-data backups; restore remaps installation paths. Portable stream templates retain embedded files when original links are unavailable.

## Testing and upgrade

Automated checks cover delayed preparation/HTTP acknowledgement, cancellation, real bundle workers and immutable versions, fresh source composition, external input folders, replay, backup path remapping, portable templates, keyboard navigation and actual interface DOM events. Windows/macOS/Linux release checks gate publication. Real SAS execution and desktop visual acceptance remain for testing on the target Windows computer; the development Mac was locked during review.

Extract into a fresh folder. Close the prior app before pointing Settings → Storage and cleanup at your existing Tasks and Settings folders, then restart. Keep the prior installation and a saved-data backup while testing.

The Graph tab remains the task editor introduced in preview.37; connecting its tasks to `engine.py` remains a later step. Existing Run, watcher, Excel scheduler and terminal workflows remain available.

Read the [workbench guide](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.38/docs/ui-workbench.md) and [Run stream guide](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.38/docs/run-stream.md), both included in the ZIP.
