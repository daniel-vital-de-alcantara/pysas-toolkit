# Single-file initialization and parameters

Workbench preview.33 fixes a mismatch in single-file runs: Settings listed `_*.sas` files from the shared initialization folder **and** watcher inbox, while Run only passed the shared folder to the engine. Inbox libraries/macros could therefore be missing, with or without parameters enabled.

Run now uses the same two initialization locations as the watcher. It reads `_*.sas` files from both folders, sorts by filename without case sensitivity, removes duplicate references to the same file, and appends them in this order:

1. Shared initialization files, such as `_10_libs.SAS` and `_20_macros.sas`.
2. The current parameter editor contents, when enabled.
3. The selected SAS program.

All of this is one SAS submission and one running job. Reading the inbox does not queue, claim, move or execute its ordinary job files. Initialization is not run separately. Shared WORK settings retain their existing placement before initialization and before parameters/program code.

Before launching, Run shows the effective shared initialization list. An explicit initialization override, or the default override saved in Settings, still replaces the automatic `_*.sas` list. Run shows that override even when Advanced execution options is collapsed. Parameters follow the override. Selecting a parameter file does not itself turn off initialization.

Console now records the folders searched, the initialization files actually appended, then parameters and the target program. Inspect the exported code under the run's `code` folder to see the submitted source. When the run fails, `_submitted.sas` also remains available.

For example:

```text
Settings > Shared initialization: C:\SAS\shared
Settings > Watcher inbox:        C:\SAS\inbox

shared\_20_macros.sas
inbox\_10_libs.SAS
saved parameters: _cases.sas
target program: extract.sas

Submission order:
_10_libs.SAS → _20_macros.sas → _cases.sas → extract.sas
```

The selected program's own folder is not another automatic initialization location. If its `_*.sas` files live elsewhere, choose that folder as Shared initialization in Settings, or use the explicit override. Saved parameter files remain separate from initialization. If an old `_cases.sas` remains in an initialization folder, it is still global initialization; move it out if it should only apply when selected in the editor.

The standalone CLI keeps its previous default initialization scope. To include an additional inbox explicitly:

```console
py pysas.py runner run extract.sas --init-dir C:\SAS\shared --inbox C:\SAS\inbox --parameters cases.sas
```

Without `--inbox`, the CLI keeps its existing behavior. If the same `_*.sas` file is explicitly selected as the CLI parameters file, it appears only in the parameters position. `--lib` remains the single-file initialization override. The Excel scheduler, Graph shared-setup definitions and SAS COM bridge are unchanged by this fix.

Automated checks cover parameter-enabled/disabled runs, mixed-case SAS extensions, initialization order across separate folders, overrides, parameter snapshots, the displayed file list and the existing CLI defaults. Windows tests also exercise the hidden UI worker and real cscript with substitute EG objects. Live SAS-server verification still requires the user's Enterprise Guide environment.
