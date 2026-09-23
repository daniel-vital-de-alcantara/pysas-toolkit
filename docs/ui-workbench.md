# Local workbench preview

The Workbench 0.4.0-preview.19 is a separate browser UI for the standalone PySAS
0.3.12 command-line engine. Download the Python ZIP from GitHub Releases, extract
it completely, and double-click `START_PYSAS.bat` on Windows. See
[`START_HERE.txt`](../START_HERE.txt) for setup and requirements.

## Running files and elapsed time

Overview displays every file currently running through the UI, including
watcher jobs and scheduler tasks. Clocks update every second. The watcher also
has a session clock; schedules have their own total elapsed time, separate from
parallel task durations. History retains final status and elapsed time.

Runner & watcher starts individual programs or watches `runner/inbox`.
Stop after current files requests the original watcher's graceful shutdown:
it stops claiming new files and lets active jobs finish. Closing the Windows
app window requests the same graceful shutdown. Browser mode provides Quit app.

Scheduler selects an Excel workbook and EGP project, previews the workbook,
launches tasks through the existing dependency engine, and supports continuing
previous schedule runs. The task list displays dependencies and statuses.
Continue follows the existing engine's semantics, including its skip rules.

Bundles & EGP provides all existing bundle and project commands. Save your
frequently used code folders and select one before packing, verifying, or
unpacking. Paths and the last-used folder persist in `.pysas-ui/bundle-paths.json`.
The single-file CLI supports the same behavior through optional `--root` on
bundle subcommands. Omitting it preserves the original script-folder default. Bundle unpack
always retains the engine's backup behavior. The UI confirms that restoration
will replace source files. It does not expose the CLI's `--no-backup` option.

Run history opens logs (with error/warning highlighting), submitted code,
console files, result files, and Excel previews. Previewed HTML is shown as
source text. Download generated reports to open them in their normal app.

## Parameters and reusable case lists

**Runner & watcher → Run a SAS program → Use parameters for this run** opens
an editor for normal SAS code, such as `%let` macro definitions. Initialization
files run first, followed by this code and then the selected program, in one
SAS submission. Use the variable names and value format your program expects.

Type/paste code or **Load a .sas file** (UTF-8, UTF-16 and Windows-1252 supported,
up to 128 KB). Imported files are copied into the editor; originals are not
changed. **Save parameter file** saves a reusable list, e.g. `_cases.sas`, under
`.pysas-ui/parameters`, outside shared initialization. Choose a saved file and
click **Load saved file** to replace the editor contents. The last saved
selection is remembered across restarts. Saves detect conflicting edits from
another window and require reloading or choosing a new name.

**Run program always uses the current editor contents, including unsaved
edits.** Turning off the checkbox omits the optional parameters entirely.
Each launch freezes a separate copy; later edits cannot change another job's
parameters. Inspect the completed run's `parameters/<filename>.sas` to see
what was submitted. Copies remain after successes, failures and cancellations.
Named lists, the last selection and run snapshots are included in backups;
restore preserves conflicting lists under new names.

If an old `_cases.sas` is already in a shared initialization folder, importing
it into the editor leaves that original in place. Move the old original out
of shared initialization when you want it to apply only to selected runs.

The standalone equivalent is:

```bat
py pysas.py runner run extract.sas --parameters cases.sas
```

When the CLI parameters file itself is a shared `_*.sas` file, that selected
file is excluded from the shared initialization pass and inserted once after
all other initialization. It must be separate from the main program and an
explicit `--lib` override. Watcher and scheduler execution are unchanged.

## Saved-data backups and run ZIPs

In **Files & folders**, use **Download saved data ZIP** after finishing all jobs
and stopping the watcher. Restore that ZIP in the new version or PC using
**Restore saved data**. Backups include `runs`, `runner/runs`, saved command
history and consoles, downloadable bundles, folder settings and bundle paths.
They contain your saved code, logs, results and project/workbook snapshots.

Restore adds history without deleting existing runs. Conflicting run folder
names are renamed and imported history points to the renamed folders. Folder
settings and bundle shortcuts are replaced; paths inside the old workspace
are adjusted to the new workspace. Unavailable input/init/inbox paths fall back
to the new workspace defaults and are reported for review. External input
folders, queued watcher files, app binaries and browser profiles are excluded.
No imported command starts automatically. Backup ZIPs and their expanded
contents are limited to 10 GB and 200,000 files. Symbolic links are excluded.

For the first upgrade from preview.17 or older, close PySAS and copy the new
app files into the existing workspace, keeping `.pysas-ui`, `runs` and
`runner/runs`. You can then export a backup. Alternatively copy those three
data locations into the newly extracted app before launching it.

**Inspect → Download entire run folder ZIP** downloads all files beneath that
run, including logs, code, results and schedule snapshots. It is independent
of the inspector's 1,000-file display limit. A ZIP of an active run contains
only the output available at download time. These ZIPs are for accessing run
files; use the saved-data backup for importing settings and command history.

## Expected duration

Use **Estimate time** before starting a program or schedule. Expected durations
also appear alongside elapsed time in active task tables and schedule cards,
and alongside queued watcher files. These are estimated *total* durations, not
remaining-time countdowns. They never change scheduling or SAS execution.

The UI reads successful saved UI runs and existing CLI run folders. It takes
the median of the ten most recent matching program names and section/row
selections. Older scheduler CSVs recover their selections from the saved Excel
workbook. Original 0.3.2 scheduler h/m/s columns and watcher start/finish
timestamps are also supported. Failed, cancelled and skipped executions are excluded from samples.
Different code or data with the same name/selection can take a different time;
the UI describes this limitation. No fuzzy name matching or code-identity
claim is made. Workspace history is refreshed in the background every 30 seconds.

Whole-schedule estimates simulate workbook-order dispatch with dependencies
and the selected parallel limit. Always-run setup is already included in task
timings; it is not counted as another task. Skipped rows take zero execution
time while preserving their dependency barriers. With missing timings, the
estimate is a lower bound from known dependency paths and known work divided
by parallel capacity, shown as e.g. **~5h+**. Entirely unknown work is labelled
unknown. Server contention, changed inputs and errors can change actual times.

## Architecture

- `ui_parameters.py`: named SAS parameter files, validation and edit conflict checks.
- `ui_data.py`: portable backup/restore, full run ZIPs and historical estimates.
- `pysas_ui.py`: standard-library HTTP server bound to loopback, constrained
  command arguments, subprocess management, history/files and previews.
- `ui_worker.py`: loads the workspace's `pysas.py` in a separate
  process; wraps entry/exit of run functions to emit observation events.
  Original function arguments, return values, exceptions and scheduler
  decisions remain under the engine's control.
- `ui/`: bundled HTML, CSS and JavaScript, with no CDN/network dependencies.
- `.pysas-ui/`: private runtime metadata and command console files, ignored
  by Git and excluded from release ZIPs.

POST requests require a per-server token and same-origin validation. Host
validation also rejects non-loopback hostnames. Runner and history paths are restricted to the selected workspace. Bundle
operations can use an explicitly chosen code folder outside the workspace;
bundle/output filenames are restricted to that code folder. The UI does not accept arbitrary shell commands.

The Files & folders page persists input/init/inbox locations in
`.pysas-ui/folders.json`. Configured input folders join the workspace as allowed
read roots for file selectors and previews. Results remain in the workspace.
The UI passes `--init-dir` and `--inbox` to the single-file engine.

Multi-file uploads stream into temporary files in the selected destination,
then rename after completion. Incomplete files are removed; name collisions are
rejected. Uploading to the watcher can execute jobs automatically. Upload shared
initialization files first. Uploads accept the supported SAS/EGP/workbook/text
formats, up to 512 MB each.

`ui_support.py` owns uploads and a Windows keep-awake controller. A dedicated
thread sets `ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED`; disabling
or shutting down clears the request on that same thread. This is an opt-in,
session-only setting with no generated mouse/keyboard input. It cannot override
manual sleep/lid-close or managed lock policies. See Microsoft's
[API documentation](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate).


Only UI-launched jobs are monitored live. Existing completed runs are imported
from `status.txt` and `run_summary.csv`. Old schedule summaries contain per-task
times but no trustworthy wall-clock total, so that total is left blank.
Unknown/incomplete folders are never labeled successful just because they
exist. After an interrupted server session, unresolved commands display Unknown.

Bridge progress is visible during execution; full SAS logs are saved after EG returns. The
adapter adds live start/finish observations; it does not change that output
behavior or add calendar scheduling. The engine's documented limitations apply.

## Development and packaging

```sh
python3 -m unittest discover -s tests -v
node --check ui/app.js
node --test tests/test_ui.cjs
python3 tools/package_release.py
```

No frontend build is required. Packaging uses an explicit list of source and
UI files, never a recursive workspace archive. GitHub Actions tests the UI on
Windows, Linux, and macOS and publishes the Python ZIP plus SHA256SUMS for
`v0.4.*` tags. Previews are marked as prereleases.

SAS Enterprise Guide integration must be tested on a configured Windows
machine; CI uses fake jobs to verify monitoring and shutdown without SAS.

Custom watcher inboxes keep their temporary claimed jobs in `.pysas-claimed`
inside that inbox, so claiming works across local drives and network shares.
The default inbox retains the existing `runner/claimed` location.

## Windows app window

The default Windows launcher uses Edge/Chrome application mode with an isolated
profile in `.pysas-ui/app-profile`. It needs no added Python UI dependency and
keeps the existing local-server architecture. Normal browser mode remains
available through `START_PYSAS_BROWSER.bat` or `--browser`; `--no-browser` remains
available for manual previews. macOS/Linux retain their previous behavior.
The terminal closes once startup succeeds. Each workspace has its own PySAS
taskbar identity and blue icon. Closing the app requests watcher shutdown and
waits for current jobs before exiting. In browser mode use Quit app; closing
a browser tab leaves the server running. START_PYSAS_CONSOLE.bat retains the
console for troubleshooting, with startup logs in .pysas-ui/launcher.log.
The window does not install a PWA or
change the user's default browser. Discovery tries standard Edge/Chrome install
folders and PATH, preferring Edge. Launch failures try the next available engine.

## Inspecting running output and stopping a file

Open Inspect on a running file. The file list and selected preview refresh every
two seconds. Logs show their latest 60 KB, with the last file update time;
scroll up to read earlier lines without the viewer jumping back down. The
Download link retrieves the complete file. The execution console now streams
as automation writes it. A quiet console does not prove SAS is stuck.

The experimental PowerShell live-SAS-log mode has been removed after reports of
runs hanging. UI and CLI use the same standard VBScript automation bridge.
Console stages update without polling EG's COM objects during execution. Full
remote SAS logs become available when EG exports them after the program returns;
this version does not promise live remote SAS log streaming.

Elapsed counters use a monotonic clock, independent of status requests. Unchanged
run lists are not rebuilt on each poll. Folder/history scans run in the background,
so a slow network folder cannot block command status updates. Use Refresh to request
fresh listings; background scans may take a moment to finish.

**Stop file** targets only that file's local automation process and descendants,
not the watcher or other running files. A stopped task is CANCELLED; normal
scheduler dependencies and stop-on-error rules still apply. Partial SAS outputs
may remain. Terminating the client is not confirmation that a remote SAS server
has cancelled an outstanding operation; verify that session in EG if necessary.

## Downloading bundles

After a successful pack, its command card has **Download bundle**. Each completed
command retains its own download copy, including bundles created in custom code
folders. Later rebuilds do not change earlier downloads. Copies are stored under
`.pysas-ui/artifacts/` and may be removed when no longer needed.

Text previews recognize UTF-8, BOM-marked UTF-16, common unmarked UTF-16 layouts,
and Windows-1252. New submitted-code exports are UTF-8. Existing source files
are not rewritten by previewing or downloading them.

Every runner job saves an original source copy in its run folder under `source/`,
including jobs stopped before EG can export code. Failed/cancelled runs also
retain `_submitted.sas` with shared initialization included.

Scheduler task rows show the selected workbook section or the configured inclusive source
row range beside the program name in Running now, schedule activity and the
inspector. Open-ended ranges and whole-program runs are labelled explicitly.
This is the selected execution range, not a live SAS line counter. The metadata
is retained for new UI runs; older runs without it do not invent a range.

### Scheduler execution

Scheduler and Continue use the same standalone engine, with a default of **10**
parallel tasks and no engine selector. Shared setup is prepended before each
target in workbook order. Both setup and targets support actual named-section
selection or inclusive row ranges. Task rows show scope, setup and execution
stage as well as elapsed time. See [the execution investigation](execution-investigation.md)
for the comparison against the user's supplied Rich-terminal source.

SAS workers now have a real Windows console, kept hidden, with normal console input. cscript inherits that console as it does in a terminal launch. The watcher receives stop requests through a separate control file. The app still opens without persistent visible terminals; closing the startup terminal does not remove the worker console. The command console records the actual engine version and whether its console was attached.

## Preview.16: schedule stop and skipped prerequisites

Each active Scheduler/Continue card and its Console view has **Stop schedule**.
It prevents further launches, cancels that schedule's active local automation
processes, then saves a stopped summary and final elapsed time. Other commands
are independent. The control shows **Stopping schedule…** until completion.

Skipped normal rows show Pending while their prerequisites are unfinished, with
a note that they will be skipped. They become Skipped only after those parents
succeed. Descendants therefore wait for the entire dependency chain. Failures
propagate through skipped rows as Blocked. Setup definitions remain Shared setup.

## Full schedule log

Each new schedule or continuation writes `schedule.log` beside its summaries
when the run finishes or is stopped. It combines every available task SAS log
and automation console, grouped in workbook order. Each task section includes
its ID, program, selected section/rows, final status and elapsed seconds. Skipped,
blocked and cancelled tasks are listed even when no SAS log was produced.
Shared setup is covered by the target programs' logs, as it runs in their submissions.

Choose **Download schedule log** on the command card or in Console, or open the
schedule in History and select `schedule.log` under Logs. The downloaded file
contains the complete available output; the in-app preview can be truncated for
large files. Original task logs remain available. The combined file uses UTF-8
and reads inputs in bounded chunks, including Windows-encoded SAS logs.

This is a report after completion/stop; it does not request live remote SAS logs
or combine separate schedule runs. Existing runs from older releases retain
their individual logs.
