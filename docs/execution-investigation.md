# Scheduler repair against the actual Rich-terminal 0.3.2

## Reference correction

The previous investigation compared against the repository's 951-line 0.3.2.
That was **not the user's working terminal script**. Preview.13 and preview.14
therefore offered a misleading “Original 0.3.2” comparison engine. It has been
removed. UI and CLI now use one standalone `pysas.py`.

The user supplied a readable `pysas_v0_3_2.py`, containing 2,757 lines and the
Rich terminal implementation. Its SHA-256 and the unmodified `VBS_EGP_RUNNER`
string are retained in `tests/fixtures/reference_032_source.json` and
`tests/fixtures/reference_032_scheduler.vbs`. These test fixtures are not
included in the release ZIP. The other supplied file was encrypted, and was
not used as source.

## Concrete execution differences repaired in preview.15

| Behavior | Actual working terminal 0.3.2 | Earlier UI engine | Repaired engine |
| --- | --- | --- | --- |
| SAS server | New code inherits the target program's `Server` | Never assigned `Server` | Assigns target server; watcher uses template seed server |
| Named sections | Extracts only code between exact section markers | Treats section as display metadata; could run the whole program | Uses the reference's section extraction and validation |
| Row ranges | Inclusive; rejects bounds outside source | Silently truncated excess end bounds | Uses reference range extraction and errors |
| Always-run setup | Each selected definition prepended in workbook order, same submission | Shared mode omitted section selection; comparison mode ran separate jobs | Prepends definitions, including their sections/ranges, once per target; never separate sessions |
| SAS error controls | `iomlogautoflush`, optional `errorabend errorcheck=strict`; setup flags propagate | `stop_program_on_error` unused | Restores options and effective setup/target flags |
| Task directory | cscript runs in isolated task folder | Inherited workspace directory | Uses isolated task folder |
| Log saving | Failing to save the SAS log fails the task | Warning could still produce SUCCESS | Log save failure returns FAILED |
| Scheduler outputs | Saves log and submitted code | Also enumerated/exported results | Matches terminal scheduler; watcher retains result/table exports |
| Concurrency | Workbook maximum or 10; explicit override possible | UI previously used 2, then confusing engine-dependent defaults | UI defaults to 10; CLI honors workbook or defaults to 10; `--max-parallel` remains accepted |

These are demonstrated discrepancies in execution, not conclusions inferred
from the elapsed timer. Missing server assignment and submitting more code
than selected can change the actual SAS work. We cannot attribute the user's
specific server wait to one of them without running that workload.

## Progress and completion

The task row shows the selected section or rows, setup definitions and current
stage: preparing, appending setup, opening EG, running the selected program,
saving the log and closing. These milestones come from the executing bridge.
Setup rows are labeled Shared setup and never appear as running sessions.
The elapsed clock uses the task's original start time and runs independently
of status polling. It stops when the task completes.

The hidden Windows worker console, file-based console/events, per-file stop,
watcher controls and UTF-8 code exports remain. Observation never polls EG COM
while synchronous `Run` is in progress. Full remote SAS statement logs still
become available when EG exports them; progress messages are not a live SAS
statement log. No shared server folder or remote log service is assumed.

## Regression evidence and limits

Windows tests execute **both** the supplied reference VBScript and the repaired
bridge with the same code/server fixtures and compare their submitted text.
Only EG COM is substituted. Real cscript, VBScript selection, XML/UTF-8/ANSI IO,
server assignment, working directories and process exit are exercised.
The substitute deliberately defaults to the wrong server and rejects execution
unless the correct server is copied. It also rejects execution outside the
task directory or repeated submission of the same task.

Cases cover three setup definitions, named sections, inclusive/open-ended
ranges, full programs, missing/duplicate markers, duplicate names, invalid
ranges, stop options from target/setup, COM execution errors and log-save
failures. A full UI → worker → scheduler → cscript test checks that three setup
definitions and a section task finish with SUCCESS in the UI. Separate tests
exercise ten concurrent jobs, dependencies, continuation, cancellation,
encoding, elapsed counters and real hidden Windows console inheritance.

Hosted CI has no licensed Enterprise Guide/SAS server. These checks validate
submission parity and UI completion with a COM substitute; the user's real
server workload is not certified by them. The release does not invent success
or impose an arbitrary time limit on long-running SAS work.
