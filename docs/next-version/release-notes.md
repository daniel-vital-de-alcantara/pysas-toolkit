# Workbench 0.4.0-preview.30

Testing preview: `0.4.0-preview.30`, with standalone engine 0.3.15. Includes the four Workbench phases plus the EGP extraction fix requested after review. The user authorized publishing this preview; the draft PRs remain unmerged.

- Fixed EGP extraction to recover program labels and classic/newer process-flow membership, as in MagicRoot. Flat and grouped source views retain original bytes/encodings; duplicate labels, unmapped programs and missing linked code are explicit. Repacking supports edits from either view and detects conflicts. Projects can inspect and ZIP the complete output. See [EGP extraction](../egp-extraction.md).
- Six pages: Overview, Run, Projects, Run History, Servers and Settings. Run guides single-file, new-schedule and continued-schedule execution. Global folder, default EGP, shared WORK, watcher, cleanup, backup and power settings are together.
- Header elapsed identifies the longest active run and excludes schedule pauses. The finish estimate covers current workloads. Storage refresh retains the last measurement; log inspection and scans refresh independently of live command status.
- Optional editable run names do not rename run folders. Continued schedules retain them. History sorts by latest activity and preserves original start time.
- The inspector occupies the work area, with Files, Logs and Tasks, Back/Escape, typed file groups, full-run ZIP, Explorer opening, actual-file copy/download and a separate displayed-log-text copy action. File listings explicitly stop at 1,000 items; the complete run remains available through ZIP/Explorer.
- Projects emphasizes Pack/Unpack with ten recent code folders. Unpack verifies before writes, preserves backups, reports engine-derived added/changed counts and retains files absent from the bundle. Bundle artifacts offer Download/Copy file. EGP and remaining flags remain available.
- Prepared ZIPs can run alongside unrelated commands. Exported schedules remain protected from continuation, and backup contents exclude newly started output folders. Restoring preferences never starts a watcher.
- Servers refreshes assigned libraries, one library's tables and one table's columns independently. Siblings and timestamps survive partial failures. Unreadable members remain visible with unknown metadata and warnings. Initialization can be omitted for a fresh-session refresh.
- Read-only table previews use saved identifiers and typed structured filters (AND/OR), default to 100 rows and cap at 1,000 rows, 100 columns, 256 characters per text cell and a 2 MB log transport budget. Numeric values are raw SAS numbers; formats accompany the schema. No ordering or random sampling is implied; filters may still scan the source on the server. Returned samples are saved locally and included in saved-data backups. CSV/JSON exports contain only returned rows.
- Dictionary search spans selected libraries, displays missing/stale/inaccessible metadata, and exports CSV or Excel. Missing schemas are collected serially in batches of at most 200 tables, with per-table stop controls. Limits: 10,000 columns per table and 100,000 saved columns per connection; overflow is explicitly partial. CSV prefixes formula-like text for spreadsheet safety; Excel exports store strings as text.

## Compatibility and outstanding acceptance

The standalone CLI, dependency/skip rules, prepended always-run definitions, concurrency defaults, error handling and saved continuation state remain intact. Engine 0.3.15 adds the labeled EGP extraction/repack workflow and retains the bundle-result observation hook. SAS execution and scheduling behavior are unchanged. Existing run folders, catalogs and saved-data backups remain readable. New preferences are optional in older backups; missing external defaults reset safely and watcher startup is disabled after restore.

External `.sas` schedule sources remain unexposed: workbook tasks currently address EGP nodes and inherit their server mapping. Defining a new external-source root and server mapping requires a separate engine/schema decision. No unsupported source-mode selector is shown.

Automated tests and fake Windows/EG tests do not establish live SAS compatibility. See [Windows/EG acceptance](windows-eg-acceptance.md). Screenshot/layout verification is pending because the development Mac is locked. The user requested publication as a testing preview after the EGP fix; live/visual acceptance remains recorded in the checklist, and the code review PRs are still unmerged.

## SAS query references

The generated query design uses [PROC SQL output limits](https://support.sas.com/documentation/cdl/en/proc/61895/HTML/default/a002473669.htm) to bound returned rows and [single-quoted SAS name literals](https://support.sas.com/documentation/cdl/en/lrcon/65287/HTML/default/p18cdcs4v5wd2dn1q0x296d3qek6.htm) for catalog identifiers. Output limits do not promise bounded server scanning. Query syntax and transport still require testing against the user's actual SAS/EG environment.
