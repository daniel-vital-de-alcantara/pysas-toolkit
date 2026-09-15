# Scheduler schema

PySAS 0.3.5 reads an Excel workbook and uses the worksheet named `Schedule` when it exists; otherwise it reads the first worksheet.

The public repository includes [`examples/schedule_example.csv`](../examples/schedule_example.csv) as a sanitized example. To use it as a workbook template, open it in Excel, save it as `Schedule.xlsx`, and name the worksheet `Schedule`.

## Required columns

| Column | Expected value | Meaning |
| --- | --- | --- |
| `task_id` | Text / number-like ID | Unique identifier for the task. Dependency references use this value. |
| `program` | Text | SAS program or Enterprise Guide code item to run. |
| `depends_on` | Comma-separated IDs | Tasks that must complete before this task becomes eligible. Leave blank for root tasks. |
| `skip` | Boolean-like value | Mark the task as skipped successfully. Useful for temporarily bypassing completed or intentionally omitted work. |
| `row_start` | Integer or blank | Optional first source line to execute. |
| `row_end` | Integer or blank | Optional last source line to execute. Row bounds are inclusive. |
| `section` | Text | Free-form grouping or documentation field. |
| `stop_process_on_error` | Boolean-like value | If enabled and the task fails, PySAS stops launching additional normal tasks. |
| `stop_program_on_error` | Boolean-like value | Reserved scheduler control field in 0.3.5; retained in task metadata but not currently used to alter execution independently. |
| `max_parallel` | Positive integer | Concurrency value used when deriving the scheduler worker limit. |
| `always_run` | Boolean-like value | Shared setup definition, prepended before every normal program in the same SAS submission. Not a separate job. Explicit skip disables it. |

## Shared setup and dependencies

Enabled `always_run` rows supply EGP program text in workbook order, with their
own inclusive row ranges. They initialize libraries, macros and options in every
program's SAS session, including parallel tasks and continuation runs.
The UI and summary label these rows `ALWAYS_RUN_DEFINITION` (Shared setup).
Their dependencies do not schedule them; dependencies on definition IDs are
satisfied because setup is included in each program. Leave definition dependencies blank.

In the example, `01_setup` is shared setup. The two extraction programs run in
parallel, each with setup prepended. `04_build_features` waits for both extracts,
then quality checks and publication run in sequence. All include setup.

## Validation behaviour

Before execution PySAS 0.3.5 checks key structural conditions including:

- duplicate `task_id` values;
- dependencies that reference unknown tasks;
- invalid row ranges.

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
