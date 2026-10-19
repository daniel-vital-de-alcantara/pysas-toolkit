# Manual Windows / Enterprise Guide acceptance

Status: target-environment checks pending. The user authorized publishing preview.30 for testing after the EGP extraction fix. These manual checks still remain; draft PRs stay unmerged. Automated Windows COM tests use fake EG objects, not a production SAS server.

## UI and keyboard

- Capture Overview, Single file, New/Continue schedule, Projects, History inspector (Files/Logs/Tasks), Settings, Servers/Columns, sample results and dictionary screenshots.
- Check 100%, 150% and 200% Windows scaling and narrow windows. Inspect Back/Escape, focus return, list scroll, Alt/F10 hints and arrow-key lists. Navigation: O Overview, R Run, P Projects, H History, V Servers, S Settings.
- Confirm elapsed seconds advance smoothly during a large log preview, slow storage scan, ZIP compression and metadata refresh. Verify header elapsed/finish labels and historical pause-adjusted continuation time.

## Existing execution and storage

- Compare a normal program and representative schedule against the known working terminal engine: three always-run definitions prepended to each task, sections/rows, default ten workers, skipped intermediate dependencies, stop-on-error and global/per-file stop.
- Continue an interrupted schedule. Confirm no successful task is rerun; original start remains, active elapsed excludes the pause, latest activity moves the run up, final task folders and consolidated schedule.log retain correct attempts.
- Start watcher explicitly, then test opt-in startup and restore (must disable startup). Confirm initialization/shared WORK behavior is unchanged for runner, watcher and scheduler.
- Test default/ambiguous EGP selection; missing external folders; parameters; app restart; config-only and full backup restore on a second workspace/PC. Confirm names and recents survive without starting jobs.
- Test Pack/Unpack with spaces/network paths, corrupted bundles, overwrite confirmation, backups and counts; unchanged destination after failed verification; files absent from a bundle retained. Verify Download/Copy file and Explorer on the correct artifact.
- Export a completed run while starting an unrelated command. Confirm that command starts, is excluded from the prepared backup, and the exported schedule cannot be continued until its ZIP is ready.

## Metadata and bounded data reads

- Test library discovery with initialization on/off; verify the off case submits no `_*.sas` or shared WORK assignments. Confirm the selected EGP chooses the intended server and a new session is used.
- Refresh sibling libraries/tables concurrently. Deny one table and one library: keep readable siblings, unreadable member names, unknown sizes/counts, warnings and independent timestamps. Test an unavailable column schema and UTF-8/ANSI/UTF-16 log exports.
- Preview empty, numeric, character, date/formatted, missing-value and Unicode data. Compare AND/OR, equality/range, contains/starts and missing filters against a manual read-only query. Quotes, percent/ampersand and unusual names must remain data/identifiers.
- Verify 100 default / 1,000 maximum rows, 100-column cap, long-cell flags, transport budget, unordered sampling notice, source unchanged, exported sample parity and per-file cancellation. Check permission/connection failures are reported without stale result substitution.
- Collect multiple libraries' missing columns. Confirm serial progress, sibling retention, stop-after-current, failed-table continuation and batch/column caps. Search across tables; compare CSV/XLSX exports with displayed filters and explicit missing/stale rows.
- Confirm returned table samples are stored locally in artifacts/run logs and backups as described; use only data appropriate for the local computer.

## EGP extraction acceptance

- Extract a representative real project. Compare program labels, classic/newer flow membership and source bytes with the original/MagicRoot output. Verify duplicate names, linked-program warnings and full-folder ZIP.
- Edit one flat file, then a grouped copy, and repack into a new EGP. Open it in Enterprise Guide, confirm only intended source edits and other project elements preserved. Conflicting edits must be reported before any output is published.
