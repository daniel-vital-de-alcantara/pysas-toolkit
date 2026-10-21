# Run stream

Run stream combines an ordered list of SAS source selections into **one program**, then submits that program once through the independent `engine.py`. The existing Run, watcher, Excel scheduler and Graph continue using their existing execution path.

## Build a stream

1. Open **Run stream** (Alt, T), give the run a name and choose a connection EGP. Browse EGP uploads a private snapshot into your Tasks folder. An existing EGP in the input folders can also be selected.
2. Browse a SAS file in the first row. Add as many rows as you need, up to the 1,000-row document limit. Use the up/down buttons to reorder them or Delete to remove a row. The same file can appear more than once with different selections.
3. Choose **Whole file**, **Between lines** or **Named section** in each row. Line numbers are 1-based and inclusive; blank From means the beginning, blank To means the end. Section selection uses the scheduler's existing, case-insensitive markers:

   ```sas
   * (please do not delete) section_start: Realised;
   /* selected code */
   * (please do not delete) section_end: Realised;
   ```

   Markers must occur once each and in order. They are excluded from the submission. Missing/duplicate sections and invalid ranges stop preparation before SAS starts.
4. Place any `_libs`, `_cases` or other setup files first. **Only the listed selections are submitted.** Run stream does not discover initialization files or apply the other Run tab's parameter/shared-WORK settings. If you need those definitions, include their SAS source as rows.
5. Select HTML results, output tables, or both. The SAS log is always saved. Combining tables produces `tables.xlsx`, with uniquely named sheets and a `tables-index.json` mapping. Original table exports remain under `execution/tables/` for recovery. If a table or merge fails, readable siblings remain available and the run reports an export error.

EGP code is used to inherit a SAS Server connection, not appended to your program. If the project contains multiple SAS servers, enter the name of one uniquely named code node under Connection options. That node's existing program is not run by the engine. Enterprise Guide/server autoexec configuration still applies.

## Source and portable JSON

**Get source** creates a downloadable `.sas` containing the selected code in row order, separated by descriptive comments. It has the same content as a run launched from the same editor choices. Download and Windows **Copy file** are available next to the result.

**Export JSON** creates a self-contained document containing the EGP, original SAS file bytes, row order, whole/line/section choices, inactive selection fields and output options. Files are embedded once by checksum. **Restore JSON** uploads that document and replaces the editor only after all embedded files and choices validate. It can be used on another installation without the original source paths. The JSON may contain private SAS code and project connection information, just like its original input files; save/share it accordingly.

Each SAS input can be up to 16 MB; distinct SAS inputs together up to 16 MB, the EGP up to 64 MB, compiled code up to 64 MB, portable JSON up to 128 MB. Repeated rows can reuse one embedded file. Uploaded snapshots with the same name remain separate. Choosing an input that later changes causes validation to ask you to choose it again, rather than submitting different code silently.

The editor retains its state during navigation and status polling. Export JSON before closing the app to preserve a draft. Every started run also saves `stream.json`, which can be restored from Inspect.

## Estimates and execution

**Estimate time** first looks for successful streams with the same selected source, order, EGP/server and output options. It shows the median of up to ten recent matches. Otherwise it adds comparable program/section/line durations from earlier file/scheduler runs. Missing parts produce a `+` estimate, or an unknown estimate when there are no usable timings. These are historical forecasts, not guarantees; SAS session setup, server load and data volume can change duration. A stream's total duration is never reused as a duration for an individual row.

**Run stream** freezes the inputs and submits `source.sas` once through `engine.run_sas`. It appears as one running submission in Overview, with elapsed time, the estimate and current Enterprise Guide phase. Its folder is under `Tasks/files/<timestamp>__stream_<id>/` and contains:

- `source.sas`, portable `stream.json`, `stream-plan.json` and original files in `sources/`;
- `run.log`, showing the ordered selections, full returned SAS log and final status;
- `execution/sas.log`, HTML, individual exported tables and engine diagnostics;
- optional `tables.xlsx`/`tables-index.json`, plus status and timing metadata.

Inspect supports Outputs, Logs, actual-file Copy, downloads, Open folder and a full run ZIP. Stop file stops this stream's owned local automation; rows are parts of one submission and cannot be cancelled independently. As with the independent engine, a job already executing on a remote SAS server may outlive local cancellation. The engine saves the SAS log when Enterprise Guide returns it; it does not provide a remote live-log feed.

Full saved-data backups include stream runs and uploaded source snapshots. The portable JSON is also an independent way to move a stream between computers. Active streams are protected from run cleanup and ZIP creation until they finish.

## Validation scope

Automated tests cover source selection/order, JSON restoration across installations, encoding, output options, cancellation, table merging, estimates, history/inspector integration, backup restoration and actual editor DOM events. Windows tests exercise hidden console/cscript execution with substitute Enterprise Guide objects. Real Enterprise Guide/SAS authentication, execution and exports still require testing on the target Windows computer.
