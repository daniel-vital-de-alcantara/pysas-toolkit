# PySAS Workbench 0.4.0-preview.36

Run stream now guides you from a new/restored template through connection setup to compact source cards. Mix PC SAS files, inline code and selected EGP programs in one ordered submission.

Download **PySAS-Workbench-Python-0.4.0-preview.36.zip**, extract the whole ZIP to a writable Windows folder and open **START_PYSAS.bat**. Requires Python 3.10+, your existing Enterprise Guide installation and SAS connection. Install openpyxl for combined workbooks. The standalone CLI remains **pysas.py 0.3.18**.

## Run stream changes

- **Staged setup:** start with New run or Restore template, then a small run-name/connection card. Automatic EGP selection prefers a saved default or recently successful project. Connection options stay collapsed when a structurally usable project is found and expand when one is needed. SAS authentication is checked when the run starts.
- **Shared WORK:** the first source-area card has a checkbox and a Settings link. Enabling it prepends the chosen server path/libref and USER option before the source cards. The owning shared-WORK session must remain open.
- **Compact, draggable source cards:** Add file or code stays below the final card. Drag cards by their grips, or use their up/down buttons. Ready/incomplete/loading indicators show what each card needs; final action controls appear when all selections are valid.
- **Three source types:** browse a PC SAS file, write SAS directly in a small editor, or browse an EGP's process flows and tick embedded programs. Selected EGP programs have ordered subrows with their own run scopes. External sources are identified without fetching their original paths.
- **Multiple named sections:** detected sections appear as checkboxes. Missing/empty/duplicate sections are explained, with marker instructions when none are available. Between lines accepts either open end but requires at least one bound; use Whole file when both are blank.
- **Background preparation:** file uploads, project inspection, extraction and inline section scanning show local loading feedback while the rest of the editor stays usable. Late responses cannot replace a newer connection, restore deleted cards or discard edits made during template import.
- **Portable templates:** JSON now preserves inline code, nested EGP selections, section choices, card/program order and shared-WORK settings, with original files embedded by checksum. Earlier Run stream JSON remains importable. Each started run retains its exact source and portable template in Inspect.
- **Standalone EGP reader:** `py egp_extract.py project.egp --json` lists programs/process flows without SAS. Add `--output new-folder` to extract original source bytes, or repeat `--program ID` to select programs. The UI and terminal command use the same reader.

Run stream still submits the frozen combined program once through `engine.py`, with HTML/table options, optional combined Excel tables, estimates, elapsed time, stop, Overview and Inspect. Existing Run, watcher, Excel scheduler and Graph workflows are preserved.

## Upgrade and test

Extract into a new folder. Close the old app before pointing Settings → Storage and cleanup to your existing Tasks and Settings folders, then restart. Keep the previous installation and saved data. Replace all application files together if updating an existing folder.

Start with Get source to review a small mixed stream: setup/inline macros first, then one file section or EGP program. Verify the order before Run. Restore an earlier template, try reordering while a source is loading, and check Inspect for the submitted source and returned SAS log.

Automated checks cover the actual editor DOM, background HTTP preparation, source composition, legacy/portable restoration, process-flow extraction, encoding, output handling, cancellation, estimates, history/inspector integration and backups. The release workflow runs Windows/macOS/Linux checks before publishing the ZIP. Windows automation checks use substitute Enterprise Guide objects; production SAS execution/exports and desktop visual acceptance still require testing on the target PC. Remote SAS logs are saved when Enterprise Guide returns them.

Read the [Run stream guide](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.36/docs/run-stream.md), [EGP reader](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.36/docs/egp-extraction.md#standalone-program-reader) and [engine API](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.36/docs/engine.md). All are included in the ZIP.
