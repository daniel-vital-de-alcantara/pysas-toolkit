# Scheduler schema

PySAS 0.3.2 reads an Excel workbook and uses the worksheet named `Schedule` when it exists; otherwise it reads the first worksheet.

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
| `stop_program_on_error` | Boolean-like value | Reserved scheduler control field in 0.3.2; retained in task metadata but not currently used to alter execution independently. |
| `max_parallel` | Positive integer | Concurrency value used when deriving the scheduler worker limit. |
| `always_run` | Boolean-like value | Allows cleanup/finalisation tasks to run despite failed prerequisites where scheduler rules permit. |

## Example dependency graph

The example schedule represents this flow:

```text
01_setup
   |-- 02_extract_customers --\
   |                          > 04_build_features -> 05_quality_checks -> 06_publish_summary
   `-- 03_extract_accounts --/                              |                    |
                                                            `------> 99_cleanup <---'
```

`02_extract_customers` and `03_extract_accounts` can run in parallel after `01_setup`. `04_build_features` becomes eligible only after both extraction tasks finish.

## Validation behaviour

Before execution PySAS 0.3.2 checks key structural conditions including:

- duplicate `task_id` values;
- dependencies that reference unknown tasks;
- invalid row ranges.

Tasks whose dependency conditions cannot be resolved remain blocked rather than being launched incorrectly.

## Practical guidance

Keep task IDs stable across reruns. They are used by the continuation workflow to identify tasks that completed successfully in an earlier schedule run.

For production schedules, prefer small task units with explicit dependencies over one very large program. That makes concurrency, failure isolation and reruns easier to reason about.

Do not publish real client names, server paths, library names, credentials, production datasets or proprietary SAS code in example workbooks.
