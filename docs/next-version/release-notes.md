# PySAS Workbench 0.4.0-preview.35

Download **PySAS-Workbench-Python-0.4.0-preview.35.zip**, extract the whole ZIP to a writable Windows folder and open **START_PYSAS.bat**. Requires Python 3.10+, your existing Enterprise Guide installation and SAS connection. Install openpyxl for combined workbooks. The existing single-file CLI remains **pysas.py 0.3.18**.

## Run stream

- A separate **Run stream** tab (Alt, T). Choose/upload a connection EGP, then add SAS files as ordered rows. Move/delete rows and select whole files, inclusive line ranges (either end can be blank), or existing scheduler sections.
- **Get source** composes the selected parts into one SAS file. **Export JSON / Restore JSON** preserve every choice and embed the EGP and SAS inputs, allowing restoration on another installation. Downloads also offer Windows actual-file Copy.
- **Run stream** freezes source/configuration and calls the independent `engine.py` once. Each run appears in Overview and the existing inspector, with elapsed time, execution phase, source, consolidated log, results, file copying, folder ZIP and cancellation. Rows share one SAS session; list any setup/parameter files first.
- Independent HTML and output-table options, plus optional `tables.xlsx` consolidation with unique sheets and a source index. Original exports and readable sibling outputs survive export/merge failures.
- Duration estimates use matching successful streams, then comparable program/section/row timings. Partial history shows `+`; unknown work stays unknown. Running streams contribute to the Overview remaining-time forecast.
- Full saved-data backups include stream runs and uploaded snapshots. Active streams remain protected from cleanup and run ZIP creation.

Existing Run, watcher, Excel scheduler and Graph continue using their established engine. Run stream does not automatically add initialization, parameters or shared WORK from those tabs. Include the desired source as explicit rows.

## Validation and limits

Tests cover source composition, portable restoration, encoding, owned-process cancellation, output handling, workbook merging, estimates, history/inspect, backups and actual editor DOM events. The release workflow runs Windows/macOS/Linux tests, including hidden-console/cscript checks with substitute Enterprise Guide objects. Real SAS execution and exports require acceptance on the target Windows PC. Remote SAS logs are saved when Enterprise Guide returns; this release does not add a live remote-log feed.

Read the [Run stream guide](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.35/docs/run-stream.md), [independent engine API](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.35/docs/engine.md) and [Windows/EG acceptance](https://github.com/daniel-vital-de-alcantara/pysas-toolkit/blob/v0.4.0-preview.35/docs/next-version/windows-eg-acceptance.md). All are included in the ZIP.
