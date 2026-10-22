# Run stream

Run stream combines an ordered list of SAS source selections into **one program**, then submits that program once through the independent `engine.py`. The existing Run, watcher, Excel scheduler and Graph continue using their existing execution path.

## Build a stream

1. Open **Run stream** (Alt, T) and choose **New run** or **Restore template**. The initial card contains just those choices. A new run starts with a compact name and connection card.
2. Connection selection defaults to **Automatic**. PySAS checks the saved default EGP, recently successful projects, then available input/uploaded projects. A structurally usable EGP collapses **Connection options**; if none is found, those options expand and ask for one. Browse EGP uploads a private snapshot into your Tasks folder. This check reads project metadata; Enterprise Guide authentication is checked when the run starts.
3. The source area appears once a usable connection is available. Its first card is **Use shared WORK**, with a link to its Settings. Turn it on to prepend the saved server path/libref and `options user=...` before the stream. The checkbox, path and libref are saved with the template. Shared WORK's owning session must remain open.
4. **Add file or code** creates a source card. It always stays below the last card. Choose one of three source types:

   - **SAS file**: browse a file on your PC. Its run-scope options appear after it has loaded.
   - **Write code**: enter SAS directly in the small editor, for example `%let case_ids = 12, 24;`. Give it a name to identify it in the source and log.
   - **EGP programs**: use the connection project or browse another EGP. Filter by process flow or program name, then tick one or more embedded programs. Selected programs appear as ordered subrows with their own run scopes and up/down/remove controls. Linked programs whose source is not embedded are marked unavailable; add their PC SAS files instead. The standalone [EGP reader](egp-extraction.md#standalone-program-reader) supplies the catalog and source bytes without starting SAS.

   Drag the grip at the left of a card to reorder it, or use its up/down buttons. The same file/program can appear in separate cards with different selections. Up to 1,000 submitted files/programs are supported.
5. Choose **Whole file**, **Between lines** or **Named sections** in each loaded card/program. Line numbers are 1-based and inclusive; blank From means the beginning, blank To means the end. At least one bound is required in Between lines mode; use Whole file when both would be blank. Named sections appear as checkboxes and chosen sections run in source order. Detection uses the scheduler's existing, case-insensitive markers:

   ```sas
   * (please do not delete) section_start: Realised;
   /* selected code */
   * (please do not delete) section_end: Realised;
   ```

   Markers must occur once each and in order. They are excluded from the submission. Missing, duplicate or empty sections are reported; when none are found the card shows the marker syntax. A card needs at least one selected section in Named sections mode.
6. Place any `_libs`, `_cases`, inline macro definitions or other setup first. **Only the listed selections and explicitly enabled shared-WORK setup are submitted.** Run stream does not discover initialization files or inherit the other Run tab's parameters. Include any required definitions as source cards.
7. Ready cards have a green edge/check; incomplete cards explain what is missing. Reading, extraction and inline section detection show local loading indicators. Those operations run in the background so you can name the run, add/edit other cards, reorder or remove cards while they finish. Late results cannot restore deleted cards or overwrite newer choices. The final action controls appear only when the stream is complete.
8. Select HTML results, output tables, or both. The SAS log is always saved. Combining tables produces `tables.xlsx`, with uniquely named sheets and a `tables-index.json` mapping. Original table exports remain under `execution/tables/` for recovery. If a table or merge fails, readable siblings remain available and the run reports an export error.

The connection EGP supplies the SAS Server connection. Its existing code is included only if you explicitly select programs in an EGP source card. If the connection project contains multiple SAS servers, enter the name of one uniquely named code node under Connection options. The engine inherits that node's server without running its existing program. Enterprise Guide/server autoexec configuration still applies. All selected code runs on this one connection, even when an EGP source card uses a different project.

## Source and portable JSON

**Get source** creates a downloadable `.sas` containing the selected code in row order, separated by descriptive comments. It has the same content as a run launched from the same editor choices. Download and Windows **Copy file** are available next to the result.

**Export template JSON** creates a self-contained document containing the connection EGP, original SAS/EGP bytes, inline code, card/program order, whole/line/multiple-section choices, shared-WORK configuration, inactive source drafts and output options. Files are embedded once by checksum. **Restore template** replaces the editor only after all embedded files and choices validate. If you edit while import is loading, **Use imported template** lets you apply it explicitly without discarding those edits automatically. It can be used on another installation without the original source paths. The JSON may contain private SAS code and project connection information, just like its original input files; save/share it accordingly.

Current templates use `pysas-run-stream-2`. Earlier `pysas-run-stream-1` templates remain importable; a legacy lines selection with both bounds blank is upgraded to Whole file. To preserve a restored template's connection, its embedded EGP is checked directly, even when it originally used Automatic.

Each SAS input can be up to 16 MB; distinct SAS files together up to 16 MB, each inline editor up to 1 MB (16 MB inline total), each EGP up to 64 MB, all embedded file assets up to 80 MB, compiled code up to 64 MB, and portable JSON up to 128 MB. Repeated cards can reuse one embedded file. Uploaded snapshots with the same name remain separate. Choosing an input that later changes causes validation to ask you to choose it again, rather than submitting different code silently.

The editor retains its state during navigation and status polling. Export a template before closing the app to preserve your choices. Every started run also saves `stream.json`, which can be restored from Inspect.

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

Automated tests cover staged setup, automatic EGP selection, inline code, multi-section selection, process-flow program extraction, dragging during loading, late-response protection, JSON restoration across installations, encoding, output options, cancellation, table merging, estimates, history/inspector integration, backup restoration, nonblocking HTTP preparation and actual editor DOM events. Windows tests exercise hidden console/cscript execution with substitute Enterprise Guide objects. Real Enterprise Guide/SAS authentication, execution and exports still require testing on the target Windows computer.
