# Single-file initialization, parameters and logs

In Workbench preview.34, **Run → Single file** has a visible Initialization choice:

- **Use default initialization from Settings**: uses the saved single-file override, when present; otherwise uses shared initialization.
- **Shared _*.sas files**: uses the configured initialization folder and watcher inbox, even when Settings has a saved override.
- **Single-file initialization override**: select one `.sas` file. Its contents replace the automatic shared list. It need not start with an underscore. A missing selection or unavailable file prevents launch.

Shared initialization reads top-level `_*.sas` files from both configured folders, including mixed-case `.SAS` extensions, removes duplicate references, and sorts by filename without case sensitivity. The selected program is not also included as shared initialization. Reading the inbox does not queue, claim or move ordinary job files. The program's own folder is not an extra automatic initialization location; choose it in Settings if that is where the shared files live.

## Before Run

**Files to submit, in order** comes from the same resolver used by the standalone engine. It shows every initialization file's full path, optional parameters from the current editor (including unsaved edits), then the selected program. An override is identified as replacing the shared list. The selected override survives inventory refreshes; missing files produce an error instead of silently reverting to defaults.

For example:

```text
1. Initialization: C:\SAS\inbox\_10_libs.SAS
2. Initialization: C:\SAS\shared\_20_macros.sas
3. Parameters: _cases.sas — current editor contents
4. Program: C:\SAS\extract.sas
```

Changing the source, initialization selection or parameters refreshes the plan. **Refresh file list** rechecks files edited outside the app. Run checks the current contents again. If they changed after preview, the updated plan is shown for review before another click submits. The worker also checks the plan fingerprint before Enterprise Guide starts, so it cannot silently run different initialization. Saved parameter files remain separate from shared initialization; an old `_cases.sas` left in a shared folder is still global setup unless removed from that folder.

Initialization, parameters and target are prepended into **one SAS submission and one running job**. Shared WORK retains its existing placement before initialization and before parameters/target. The Enterprise Guide COM bridge, server selection and scheduler behavior are unchanged.

## Inspect and consolidated log

**Inspect → Logs → run.log** contains:

- The full ordered file list, initialization mode, snapshot locations and SHA256 hashes of submitted text.
- The preparation trace identifying each appended file.
- Complete available SAS logs and automation console output, with final status and elapsed time.

The file starts with the plan while the job is running and is consolidated after success, SAS error, cancellation or an automation exception. SAS output is available when Enterprise Guide exports it; this change does not enable live remote-server log streaming. Copy file and Download work on `run.log` as on other logs.

The run folder keeps `execution-plan.json`, initialization and parameter snapshots, the target under `source/`, and `_submitted.sas` even after success. The exported `code/` copy records what the COM bridge submitted. Folder ZIPs and saved-data backups include this evidence.

The submitted source emits `NOTE: PYSAS_FILE_START|N|role` and `NOTE: PYSAS_FILE_END|N|role`, where N matches the ordered list. These show when SAS reaches each boundary even if source echo is disabled. A plan or an appended file is not proof that SAS successfully executed it: an abort, syntax error or connection failure can prevent later code from being reached. Read the SAS diagnostics and markers together.

## Standalone CLI

The CLI retains its existing default initialization scope. Add `--inbox` explicitly to include another location:

```console
py pysas.py runner run extract.sas --init-dir C:\SAS\shared --inbox C:\SAS\inbox --parameters cases.sas
```

`--lib C:\SAS\custom_init.sas` replaces the automatic shared list. Parameters follow initialization. A CLI parameter file that is itself a shared `_*.sas` file appears only in the parameter position. Every single-file run now retains the consolidated `run.log` and submitted source, including watcher jobs. The script remains usable as a standalone file without any UI modules.

Automated checks cover the actual HTML form, DOM events and FormData, polling, stale previews, HTTP validation/download, the real Python worker and order/content of submitted code and logs. Windows checks additionally exercise real cscript with substitute EG objects, with overrides and parameters on/off. Production SAS-server and desktop visual acceptance remain listed in `docs/next-version/windows-eg-acceptance.md`.
