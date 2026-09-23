# Scheduler schema

PySAS 0.3.11 reads an Excel workbook and uses the worksheet named `Schedule` when it exists; otherwise it reads the first worksheet.

The public repository includes [`examples/schedule_example.csv`](../examples/schedule_example.csv) as a sanitized example. To use it as a workbook template, open it in Excel, save it as `Schedule.xlsx`, and name the worksheet `Schedule`.

## Required columns

| Column | Expected value | Meaning |
| --- | --- | --- |
| `task_id` | Text / number-like ID | Unique identifier for the task. Dependency references use this value. |
| `program` | Text | SAS program or Enterprise Guide code item to run. |
| `depends_on` | Comma-separated IDs | Tasks that must complete before this task becomes eligible. Leave blank for root tasks. |
| `skip` | Boolean-like value | Omit this program after its dependencies succeed. Downstream tasks still wait for all ancestors, including through other skipped rows. |
| `row_start` | Integer or blank | Optional first source line to execute. |
| `row_end` | Integer or blank | Optional last source line to execute. Row bounds are inclusive. |
| `section` | Text | Execute only the named section between its start/end markers. Mutually exclusive with nonzero row bounds. |
| `stop_process_on_error` | Boolean-like value | If enabled and the task fails, PySAS stops launching additional normal tasks. |
| `stop_program_on_error` | Boolean-like value | Enables SAS `errorabend errorcheck=strict` for the submission; enabled flags on shared setup also apply to every target. |
| `max_parallel` | Positive integer | Concurrency value used when deriving the scheduler worker limit. |
| `always_run` | Boolean-like value | Shared setup definition, prepended before every normal program in the same SAS submission. Not a separate job. Explicit skip disables it. |

## Shared setup and dependencies

Enabled `always_run` rows supply EGP program text in workbook order, with their
own named sections or inclusive row ranges. They initialize libraries, macros and options in every
program's SAS session, including parallel tasks and continuation runs.
The UI and summary label these rows `ALWAYS_RUN_DEFINITION` (Shared setup).
Their dependencies do not schedule them; dependencies on definition IDs are
satisfied because setup is included in each program. Leave definition dependencies blank.

In the example, `01_setup` is shared setup. The two extraction programs run in
parallel, each with setup prepended. `04_build_features` waits for both extracts,
then quality checks and publication run in sequence. All include setup. The
example leaves `section` blank to select whole programs; fill it only when the
matching markers exist in that EGP program.

## Validation behaviour

Before execution PySAS 0.3.11 checks key structural conditions including:

- duplicate `task_id` values;
- dependencies that reference unknown tasks;
- invalid row ranges, negative bounds and section/range conflicts;
- empty program names, duplicate columns and dependency cycles.

Tasks whose dependency conditions cannot be resolved remain blocked rather than being launched incorrectly.

## Practical guidance

Keep task IDs stable across reruns. They are used by the continuation workflow to identify tasks that completed successfully in an earlier schedule run.

For production schedules, prefer small task units with explicit dependencies over one very large program. That makes concurrency, failure isolation and reruns easier to reason about.

Do not publish real client names, server paths, library names, credentials, production datasets or proprietary SAS code in example workbooks.

## Failure and continuation behavior

A stop-on-error failure prevents new normal tasks from launching; these tasks
receive `STOPPED_ON_ERROR`. Tasks already running finish. Failed dependencies
block their dependent programs. Worker exceptions are recorded in the summary.
Shared setup is part of each submitted program, so its SAS errors are recorded
against that program. Setup definitions do not run as cleanup tasks.

Continuation skips previous successful normal tasks and keeps enabled setup
definitions available for every remaining program. Explicit skip disables setup.

## Named sections and execution settings

Section markers match the working Rich-terminal 0.3.2 syntax (case insensitive):

```sas
* (please do not delete) section_start: Realised;
/* Only the code between these markers is selected. */
* (please do not delete) section_end: Realised;
```

Exactly one start and one end are required, in that order. Marker lines are
excluded. Blank/zero row bounds mean unbounded; nonzero bounds cannot accompany
a section. Out-of-bounds rows fail before execution.

Each target inherits its original EGP code item's SAS server. All enabled setup
is prepended once, with initialization and target boundary comments, and
`options iomlogautoflush;`. If any included setup or the target enables
`stop_program_on_error`, `errorabend errorcheck=strict` is added. If an included
setup enables `stop_process_on_error`, a failure of a submitted target stops
new launches. Connection loss also stops new launches. Active tasks finish.

UI Scheduler and Continue default to 10 parallel tasks. CLI `schedule` uses the
largest workbook `max_parallel`, or 10 when all are blank. An explicit
`--workers N` (also accepted as `--max-parallel N`) overrides it.

## Skipped dependency chains

A skipped normal task stays pending until its dependencies are satisfied. It
then becomes `SKIPPED_SUCCESS` without starting Enterprise Guide. Consequently,
`A → B (skipped) → C` runs A first and starts C only after A succeeds. The same
rule applies through multiple skipped rows and branches with multiple parents,
regardless of workbook row order. Failed/cancelled ancestors block the skipped
row and its descendants. The rule also applies to rows skipped by continuation.

## Stopping a whole schedule

Use **Stop schedule** on its activity card or in its Console view. This stops
new submissions and requests cancellation of every active file in that one
schedule, including files still starting. Other schedules and watchers continue.
The button also works for a continuation run. Completed results remain saved;
remaining tasks are recorded as `CANCELLED`, and the run becomes `STOPPED` once
its workers exit. Per-file Stop still affects only that file.

Cancellation terminates each owned local automation process; as with per-file
Stop, server-side SAS termination depends on the existing EG/server connection.
Partial outputs may remain. A stopped run can be continued using its summary.

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
