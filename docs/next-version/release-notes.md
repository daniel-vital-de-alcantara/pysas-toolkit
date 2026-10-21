# PySAS Workbench 0.4.0-preview.34

Download **PySAS-Workbench-Python-0.4.0-preview.34.zip**, extract the whole ZIP to a writable Windows folder and open **START_PYSAS.bat**. Requires your existing Python 3.10+, Enterprise Guide and SAS connection. Includes standalone engine **0.3.18**.

- **Keep the selected override:** file inventory refresh could clear Run's initialization override and submit a blank value. Run now preserves that selection. Initialization is visible, with separate default/shared/single-file override choices; Shared can ignore a saved default override. Inbox files are also selectable.
- **Exact plan before launch:** the ordered list shows full initialization paths, the current parameter editor contents and the target program. Preview and worker use the same resolver. Contents are checked at launch and in the worker; changed or missing inputs cannot silently fall back to another plan. Errors appear beside the Run controls.
- **Consolidated single-file log:** Inspect → Logs → **run.log** includes the ordered file list, preparation trace, available full SAS logs, automation output, status and elapsed time. Initialization/parameter snapshots, execution-plan.json and _submitted.sas survive success, failure and cancellation. Copy/Download and folder ZIP include this evidence.
- **SAS execution evidence:** numeric start/end markers in submitted code identify when SAS reaches each source. The plan lists intended sources; SAS diagnostics and markers establish what was reached. This does not add remote live-log streaming.
- **Existing workflows retained:** one submission with initialization → parameters → target; the same COM bridge/server binding; standalone CLI defaults; watcher, Excel/Graph dependency scheduling, keyboard controls and portable Tasks/Settings folders.

## Upgrade and verify

Extract into a new folder. Close the old app before pointing Settings → Storage and cleanup to the existing Tasks and Settings folders; restart to use those locations. Keep your previous installation and saved data. If updating an existing folder, replace all application files together, including pysas.py.

On Run, select the intended Initialization mode and review **Files to submit, in order**. For an override, choose its file: that one file replaces the automatic `_*.sas` list. After the run, open **Inspect → Logs → run.log**; compare the ordered list with `code/` and the SAS diagnostics/markers.

Release checks run on Windows, macOS and Linux before the ZIP is published. They cover the real HTML form/FormData, inventory refresh, stale-plan rejection, HTTP validation/download, actual Python worker and cscript with substitute EG objects, including overrides with parameters on/off. Production SAS-server and desktop visual verification remain pending in the target environment.

Read [single-file initialization and logs](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.34/docs/single-file-initialization.md), [the Graph guide](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.34/docs/graph-runner.md) and [Windows/EG acceptance](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.34/docs/next-version/windows-eg-acceptance.md). These documents are also inside the ZIP.
