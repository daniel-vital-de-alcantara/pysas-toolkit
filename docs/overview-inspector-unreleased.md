# Overview, inspector and portable data

Included in Workbench `0.4.0-preview.32`, with the Graph tab and scoped Settings keyboard hints.

Overview owns the four status cards, with watcher stopping inside its card. The searchable Tasks table merges saved runs and command activity, including commands with no SAS run folder. A continued schedule appears once. The old History URL redirects to Overview. The app controls live at the bottom of the sidebar and disappear while inspecting.

The inspector has Back beside the title, then a consistent toolbar: Outputs (Alt F), Logs (L), Tasks (T), Open folder (O), Create ZIP (Z), editable name and result status. Controls stay in place and disable when unavailable. Successful tasks open Outputs; other statuses open Logs. Outputs excludes logs and nested task files. Logs includes task logs with short task-ID labels and green/no-diagnostic, yellow/warning or red/error symbols. Scanning is asynchronous; pending/unreadable logs have neutral indicators rather than false green checks. The diagnostic list stays expanded. Tasks uses the inspector's main scroll area; each available task folder opens its own inspector, with Back returning to the parent tab/selection. Active-file and whole-schedule stopping remain available.

Default layout:

```text
PySAS app/
  pysas.py, pysas_ui.py, ui/, ...
  tasks/
    files/<file run>/
    schedules/<schedule run>/tasks/<task ID>/
    .workbench/                 command history, artifacts and export caches
  settings/
    preferences.json, folders.json, bundle-paths.json, shared-work.json, ...
    parameters/
  .pysas-locations.json         local pointer to the two portable folders
  .pysas-ui/                   installation-specific launcher log/lock
```

In Settings → Storage and cleanup, Tasks and Settings can point to separate existing folders outside the installation. Stop jobs first; changes apply after restart. Copy the current folders first to retain their data, or point directly at folders used by a previous installation. Existing destination data is loaded, never replaced by an empty configuration. An installation-specific pointer remains necessary so the app can find external folders. One running app can write to a given Tasks/Settings folder at a time; other installations fail clearly instead of racing shared metadata.

On first upgrade, old settings and command artifacts are copied into the new layout without deleting originals. Old `runs` and `runner/runs` remain readable. **Import existing runs into Tasks** copies finished legacy runs in the background and remaps command history. Originals remain available to the CLI, while duplicate history, backup and timing entries are excluded. Active/unknown runs are protected. Existing saved-data ZIPs remain supported; restores place imported runs under Tasks. Backups, file copy/download, ZIP exports, cleanup, timing estimates and continuation resolve configured external locations.

The standalone CLI keeps its existing default folder layout. The UI supplies `PYSAS_RUNS_DIR` to its worker; callers can also explicitly set that environment variable for `files`/`schedules` output roots. SAS COM code, shared initialization and dependency execution are unchanged.

Validation: 201 Python tests (175 passed, 26 Windows-only skipped), 42 JavaScript tests, real localhost API/download tests, migration rollback, reuse from a second installation, external backups/restores and shared-folder locks. Live Windows/SAS and visual acceptance remain pending; the development Mac was locked during browser review.
