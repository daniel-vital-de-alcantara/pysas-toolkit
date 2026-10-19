# Workbench next version implementation plan

Baseline: preview.29 / engine 0.3.14. Four stacked review PRs; no merge or preview tag before review and Windows/EG acceptance.

1. Navigation and Run: six task-oriented pages, progressive single/schedule/continue forms, global Settings, default project preference, explicit watcher start and opt-in startup, header elapsed/aggregate finish, isolated storage scanning. Covers OV-01/02/03, RUN-01/02/03/04/06/07, SET-01/02.
2. History and Projects: names and activity timestamps, full-pane Files/Logs/Tasks inspector, folder opening and distinct text/file copy, recent code folders, verify-before-unpack and accurate artifact history. Covers RUN-05, PR-01/02/03/04/05, HIS-01/02/03/04/05/06/07.
3. Server metadata: connection-specific initialization, independent library/table/column refreshes and timestamps, unreadable members retained, safe partial merges. Covers SRV-01/02.
4. Data exploration: bounded typed filters, read-only sample transport/export, searchable incremental dictionary and CSV/XLSX exports. Covers SRV-03/04.

## Conservative decisions

- Aggregate ETA means time until current workloads finish; it is not a sum of parallel elapsed times. Display per-run elapsed separately, including pause-adjusted continuation time.
- Multiple files remains an Excel dependency schedule. No new ad-hoc batch runner.
- Settings can select a default EGP; otherwise require unambiguous auto detection. Never guess among unused projects on different servers.
- External schedule sources require explicit mode, confined paths and archived source before exposure. Existing embedded mode must remain byte-for-byte compatible when optional features are disabled.
- Watcher startup is opt-in, off by default and disabled after restoring settings. Moving UI controls alone never starts it.
- Bundle path is the destination/source code directory; bundle file is selected separately for unpack. Pack has a default name. Unpack never deletes files missing from the bundle.
- Server initialization is per connection/refresh; off means do not submit initialization files. Every refresh uses a fresh session, not the user's open EG session.
- Dataset previews default to 100 rows with a maximum of 1,000 rows, 100 columns and an explicit transport budget. Exports contain only the returned sample.
- Run names are metadata, editable without renaming folders; continuations retain the name.

## Validation and review gates

For every PR: relevant unit/API/UI tests, full regression suite, no accidental input/run data in commits, backward compatibility notes. Windows CI validates VBScript with fake EG; this does not replace live Windows/Enterprise Guide verification. Screenshot major UI states if desktop access is available. Record unavailable verification explicitly. Keep all PRs unmerged for review.

## Phase A review notes

Implemented six-page navigation, progressive Run flow, global Settings, saved default EGP/initialization and explicit watcher preferences. Alt O/R/P/H/V/S selects Overview/Run/Projects/History/Servers/Settings. Older #scheduler links enter Multiple files. Resumable schedule choices exclude successes and unknown/unmonitored jobs. Engine and continuation semantics are unchanged.

Refresh retains the last measurement, allows only one scan per listing, and exposes scan errors independently. Console/log inspection now refreshes outside the live-status polling guard. Header elapsed refers to the longest active run; ETA/finish refer to all current work and exclude future arrivals. Restored watcher settings always have startup disabled.

External-file schedule mode remains unexposed: existing workbook tasks address named EGP nodes and inherit their server assignment. Adding a selector without a defined external source root/server mapping would silently change execution. This requires a separate engine/schema change after the source-mode decision; the existing mode remains available.

Manual acceptance before merge/release: Windows normal run with parameters; new and continued Excel schedules; watcher explicit start/stop and opt-in startup; restore on a second PC; Alt navigation and progressive forms at 100/150/200% scaling; responsiveness with large logs and offline folders. Desktop screenshots could not be captured because the Mac is locked; no visual or live SAS verification is claimed.

## Phase B review notes

Inspector now occupies the work area with Files, Logs and Tasks navigation, Back/Escape, typed file groups, an explicit 1,000-file listing notice, folder opening and separate displayed-text versus actual-file copy. Optional names are metadata, editable without folder renames and inherited by continued schedules. History sorts by activity while preserving original start and separate active-attempt clocks.

Projects remembers ten recent folders and exposes Pack/Unpack first, with verify/output/recursive flags and EGP tools secondary. Unpack still validates before writes and keeps backups; added/changed/deleted counts come from the standalone engine observation hook. Pack, verified and unpacked bundles retain downloadable/copyable artifacts. Backup ZIP compression no longer blocks unrelated new commands; continuing an exported schedule remains protected, and the backup captures its original command metadata and excludes newly created output folders.

Manual acceptance: Files/Logs/Tasks at small and large resolutions; Back/Escape focus; Windows Explorer opening and native file copy; rename/resume; bundle overwrite confirmation, corrupt bundle, network code folder and timestamped backups; full export while starting an unrelated file. Screenshots and live Windows/EG verification remain pending on an unlocked Windows desktop.
