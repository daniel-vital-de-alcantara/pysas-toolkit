# Local workbench preview

The Workbench 0.4.0-preview.1 is a separate browser UI for the unchanged PySAS
0.3.2 command-line engine. Download the Python ZIP from GitHub Releases, extract
it completely, and double-click `START_PYSAS.bat` on Windows. See
[`START_HERE.txt`](../START_HERE.txt) for setup and requirements.

## Running files and elapsed time

Overview displays every file currently running through the UI, including
watcher jobs and scheduler tasks. Clocks update every second. The watcher also
has a session clock; schedules have their own total elapsed time, separate from
parallel task durations. History retains final status and elapsed time.

Runner & watcher starts individual programs or watches `runner/inbox`.
Stop after current files requests the original watcher's graceful shutdown:
it stops claiming new files and lets active jobs finish. Closing only the
browser does not stop the server or its jobs. Keep the launcher open.

Scheduler selects an Excel workbook and EGP project, previews the workbook,
launches tasks through the existing dependency engine, and supports continuing
previous schedule runs. The task list displays dependencies and statuses.
Continue follows the existing engine's semantics, including its skip rules.

Bundles & EGP provides all existing bundle and project commands. Bundle unpack
always retains the engine's backup behavior. The UI confirms that restoration
will replace source files. It does not expose the CLI's `--no-backup` option.

Run history opens logs (with error/warning highlighting), submitted code,
console files, result files, and Excel previews. Previewed HTML is shown as
source text. Download generated reports to open them in their normal app.

## Architecture

- `pysas_ui.py`: standard-library HTTP server bound to loopback, constrained
  command arguments, subprocess management, history/files and previews.
- `ui_worker.py`: loads the workspace's original `pysas.py` in a separate
  process; wraps entry/exit of run functions to emit observation events.
  Original function arguments, return values, exceptions and scheduler
  decisions remain under the engine's control.
- `ui/`: bundled HTML, CSS and JavaScript, with no CDN/network dependencies.
- `.pysas-ui/`: private runtime metadata and command console files, ignored
  by Git and excluded from release ZIPs.

POST requests require a per-server token and same-origin validation. Host
validation also rejects non-loopback hostnames. Paths are restricted to the
selected workspace. The UI does not accept arbitrary shell commands.

Only UI-launched jobs are monitored live. Existing completed runs are imported
from `status.txt` and `run_summary.csv`. Old schedule summaries contain per-task
times but no trustworthy wall-clock total, so that total is left blank.
Unknown/incomplete folders are never labeled successful just because they
exist. After an interrupted server session, unresolved commands display Unknown.

The existing engine captures Enterprise Guide output until completion. The
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
