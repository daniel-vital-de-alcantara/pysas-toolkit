"""Observation adapter for the standalone PySAS engine. Runs in a child process."""
from __future__ import annotations
import _thread
import functools
import importlib.util
import json
import os
import sys
import threading
import time
from pathlib import Path

PREFIX = "@@PYSAS_UI@@"
_lock = threading.Lock()
_context = threading.local()


def emit(event, **values):
    with _lock:
        payload = json.dumps({"event": event, "time": time.time(), **values}, default=str) + "\n"
        event_path = os.environ.get("PYSAS_UI_EVENTS")
        if event_path:
            # Observation must never wait for the UI to consume a pipe.
            try:
                with open(event_path, "a", encoding="utf-8") as output:
                    output.write(payload)
            except OSError as exc:
                sys.stderr.write(f"UI event could not be saved: {exc}\n")
        else:
            sys.stdout.write(PREFIX + payload)
            sys.stdout.flush()


def load_engine(script):
    spec = importlib.util.spec_from_file_location("pysas_engine", script)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    return engine


def observe(engine):
    """Observe tasks and progress: the standalone engine owns execution and scheduling."""
    original_job = engine.run_job
    @functools.wraps(original_job)
    def job(source, *args, **kwargs):
        key = str(source)
        _context.key = key
        emit("start", key=key, name=Path(source).name, kind="file")
        try:
            result = original_job(source, *args, **kwargs)
        except BaseException as exc:
            emit("finish", key=key, name=Path(source).name, status="FAILED", message=str(exc))
            raise
        emit("finish", key=key, name=result["name"], status=result["status"],
             elapsed=result["elapsed"], path=result["run_dir"])
        return result
    engine.run_job = job
    original_task = engine.scheduler_task
    @functools.wraps(original_task)
    def task(definition, project, task_root):
        key = definition["task_id"]
        _context.key = key
        path = task_root / engine.safe_name(key)
        emit("start", key=key, name=definition["program"], kind="task", path=path,
             section=definition.get("section", ""), row_start=definition.get("row_start"), row_end=definition.get("row_end"),
             setup=[{k: row.get(k) for k in ("task_id", "program", "section", "row_start", "row_end")} for row in definition.get("_always_run", [])])
        try:
            result = original_task(definition, project, task_root)
        except BaseException as exc:
            emit("finish", key=key, name=definition["program"], status="FAILED", message=str(exc), path=path)
            raise
        emit("finish", key=key, name=definition["program"], status=result["status"],
             elapsed=result["elapsed"], path=result["task_dir"], message=result["message"])
        return result
    engine.scheduler_task = task
    original_load = engine.load_schedule
    @functools.wraps(original_load)
    def load(path):
        tasks = original_load(path)
        emit("plan", tasks=tasks)
        return tasks
    engine.load_schedule = load
    original_execute = engine.execute_eg
    @functools.wraps(original_execute)
    def execute(mode, project, sas_path, program, row_start, row_end, run_dir, tables):
        if getattr(_context, "key", None):
            emit("location", key=_context.key, path=run_dir)
        return original_execute(mode, project, sas_path, program, row_start, row_end, run_dir, tables)
    engine.execute_eg = execute
    if hasattr(engine, "report_progress"):
        original_progress = engine.report_progress
        @functools.wraps(original_progress)
        def progress(run_dir, phase, message):
            original_progress(run_dir, phase, message)
            if getattr(_context, "key", None):
                emit("progress", key=_context.key, phase=phase, progress=message, path=run_dir)
        engine.report_progress = progress
    original_summary = engine.write_summary
    @functools.wraps(original_summary)
    def summary(path, results):
        original_summary(path, results)
        emit("summary", path=path, tasks=results)
    engine.write_summary = summary


def prepare_console():
    """Restore real console input before cscript inherits it; UI controls use a file."""
    if os.name != "nt" or os.environ.get("PYSAS_UI_CONSOLE") != "1":
        return False
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetConsoleWindow.restype = wintypes.HWND
    kernel.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
    kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    if not kernel.GetConsoleWindow():
        raise RuntimeError("The SAS worker has no Windows console; execution was not started.")
    fd = os.open("CONIN$", os.O_RDWR)
    try:
        os.dup2(fd, 0)
    finally:
        if fd != 0:
            os.close(fd)
    handle = msvcrt.get_osfhandle(0)
    if not kernel.SetStdHandle(-10 & 0xffffffff, handle):
        raise ctypes.WinError(ctypes.get_last_error())
    mode = wintypes.DWORD()
    if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
        raise RuntimeError("The SAS worker's input is not a Windows console.")
    # Selection in a console must not suspend a long-running job.
    kernel.SetConsoleMode(handle, (mode.value | 0x80) & ~0x40)
    return True


def main():
    script, *arguments = sys.argv[1:]
    console = prepare_console()
    engine = load_engine(Path(script))
    emit("worker", engine_version=getattr(engine, "VERSION", "unknown"),
         script=str(Path(script).resolve()), python=sys.executable, pid=os.getpid(),
         console=console, arguments=arguments)
    print(f"PySAS engine {getattr(engine, 'VERSION', 'unknown')} | console={'attached' if console else 'inherited'}", flush=True)
    observe(engine)
    if arguments[:2] == ["runner", "watch"]:
        def control():
            control_path = os.environ.get("PYSAS_UI_CONTROL_FILE")
            if control_path:
                while not Path(control_path).exists():
                    time.sleep(.1)
                _thread.interrupt_main()
            else:
                for line in sys.stdin:
                    if line.strip() == "stop":
                        _thread.interrupt_main()
                        return
        threading.Thread(target=control, daemon=True).start()
    return engine.main(arguments)


if __name__ == "__main__":
    sys.exit(main())
