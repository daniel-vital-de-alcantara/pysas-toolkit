# PySAS Workbench 0.4.0-preview.33

Download **PySAS-Workbench-Python-0.4.0-preview.33.zip**, extract the entire ZIP to a writable Windows folder and open **START_PYSAS.bat**. Requires your existing Python 3.10+, Enterprise Guide and SAS connection. Includes standalone engine **0.3.17**.

- **Single-file initialization fixed:** Run previously omitted `_*.sas` files in the watcher inbox, even though Settings listed them. It now combines files from the shared initialization folder and watcher inbox, alphabetically, before parameters and the selected program. Applies with parameters enabled or disabled. Mixed-case `.SAS` extensions are supported.
- **Visible preparation:** Run shows the effective initialization list or override before launch. Console records each appended initialization file, parameters and target in order. An explicit override, or a default override from Settings, still replaces the shared list and is now clearly identified.
- **Existing CLI defaults retained:** the standalone single-file command only includes the inbox when `--inbox` is supplied explicitly. Reading initialization does not queue or move ordinary inbox jobs. The watcher, Excel/Graph dependency scheduling and SAS COM bridge retain their execution behavior.
- **Existing features included:** Graph canvas/JSON runs, ordered shared setup, 10 default parallel schedule jobs, source snapshots, scoped Settings keyboard hints, portable Tasks/Settings folders, searchable Overview Tasks and Outputs/Logs/Tasks inspectors.

## Upgrade and verify

Keep the existing installation and saved data. Extract this ZIP to a new folder and close the previous app before pointing Settings > Storage and cleanup to the existing Tasks and Settings folders; restart to apply those locations. Full backups/restores remain available. Replace all application files together when updating an existing installation, including pysas.py.

Before Run, check the initialization list. For example, `_10_libs.SAS → _20_macros.sas`, then your parameters and target. If an initialization override is shown, that one file replaces the automatic shared list. Source-folder neighbors are not automatically added; set Shared initialization in Settings to the folder containing those files.

Automated release checks run on Windows, macOS and Linux before the ZIP and SHA256SUMS.txt are published. Regression coverage includes parameters on/off, separate initialization/inbox folders, order, overrides, snapshots and the unchanged CLI defaults. Windows tests exercise the hidden UI worker and real cscript with substitute EG objects. Actual Enterprise Guide/SAS server and desktop visual verification still require the target environment.

Read [single-file initialization](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.33/docs/single-file-initialization.md), [the Graph guide](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.33/docs/graph-runner.md) and [Windows/EG acceptance](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.33/docs/next-version/windows-eg-acceptance.md). These documents are included inside the ZIP.
