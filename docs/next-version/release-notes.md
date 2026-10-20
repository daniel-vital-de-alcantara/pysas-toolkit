# PySAS Workbench 0.4.0-preview.31

Download **PySAS-Workbench-Python-0.4.0-preview.31.zip**, extract the entire ZIP to a writable Windows folder and open **START_PYSAS.bat**. Requires your existing Python 3.10+, Enterprise Guide and SAS connection. This is a testing preview with standalone engine **0.3.16**.

- **Graph tab:** build a dependency canvas from linked SAS files or uploaded SAS/EGP sources. Drag cards, link prerequisites, select sections/rows, reorder shared setup and save/import/export JSON. The existing Run tab and Excel schedules remain available.
- **One scheduler:** graphs use the existing execution queue, default 10 parallel programs, skipped-dependency barriers, elapsed time, logs, stopping and continuation. Shared setup is prepended into each target submission. Embedded EGP programs keep their original server connection. JSON graph execution does not require openpyxl.
- **Frozen runs:** graph source, selected code and connection templates are saved before execution. Continue uses that snapshot, retains successful task outputs and counts active time without the pause. Source hashes are retained; automatic changed-source-only reruns are a future feature.
- **Settings keyboard hints:** Alt, S first chooses a section: F Folders, D Defaults, W Shared WORK, I Inbox watcher, S Storage, U Uploads, B Backups or P Power. Only that section's actions then receive hints. Escape returns one level. Off-screen sections remain reachable, and the help wraps in narrow windows.
- **Overview and inspectors:** the four status cards appear only in Overview. One searchable Tasks list combines runs and command activity. Inspectors have consistent Outputs / Logs / Tasks / Open folder / Create ZIP controls, diagnostic indicators, an expanded issues list and individual task inspectors.
- **Portable data:** Tasks and Settings have dedicated folders, with configurable external locations applied after restart. Legacy runs remain readable and can be copied into Tasks. Full backups include graph uploads and frozen runs; configs-only includes graph definitions. Collisions are preserved under separate names.

## Upgrade

Keep your existing installation and saved data. Extract this ZIP into a new folder. To reuse data already in the new portable layout, close the other app and select its Tasks and Settings folders in Settings > Storage and cleanup, then restart. For older layouts, use a saved-data backup/restore or copy the new app files into the existing workspace while it is closed; legacy data is retained. Uploaded graph sources travel in a full backup. Linked external SAS/EGP files must be copied separately or relinked on another PC.

## Verification and limits

The release workflow runs Python and JavaScript checks on Windows, macOS and Linux before publishing the ZIP and SHA256SUMS.txt. Windows tests exercise real cscript with substitute Enterprise Guide objects. They do not establish live SAS-server compatibility. Desktop visual acceptance and live Enterprise Guide/SAS tests remain pending; the development Mac was locked during visual checks.

Graph limits include 200 program cards, 100 shared setup definitions, 2,000 links, 32 workers and 16 MB per SAS source. External/linked EGP code needs an actual SAS file; duplicate embedded program names must be renamed in EG before running. Stopping ends owned local automation processes; remote SAS cancellation is not guaranteed.

See [the Graph guide](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.31/docs/graph-runner.md), [portable data and inspectors](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.31/docs/overview-inspector-unreleased.md), [EGP extraction](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.31/docs/egp-extraction.md) and [Windows/EG acceptance](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.31/docs/next-version/windows-eg-acceptance.md) inside the ZIP.
