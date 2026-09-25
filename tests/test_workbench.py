from __future__ import annotations
import contextlib
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pysas_ui as ui
import ui_worker as worker


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copy2(ROOT / "pysas.py", self.root / "pysas.py")
        self.app = ui.Workbench(self.root)

    def tearDown(self):
        deadline = time.time() + 5
        while self.app.processes and time.time() < deadline:
            time.sleep(.05)
        self.temp.cleanup()

    def wait_command(self, identifier):
        deadline = time.time() + 10
        while identifier in self.app.processes and time.time() < deadline:
            time.sleep(.05)
        self.assertNotIn(identifier, self.app.processes)
        return self.app.commands[identifier]

    def test_bundle_commands_execute_original_engine(self):
        (self.root / "example.sas").write_text("data demo; x=1; run;\n")
        result = self.app.launch({"action": "bundle-pack"})
        item = self.wait_command(result["id"])
        self.assertEqual(item["status"], "SUCCESS")
        self.assertGreater(item["elapsed"], 0)
        self.assertTrue((self.root / "codebase.sasbundle.txt").exists())
        result = self.app.launch({"action": "bundle-verify"})
        self.assertEqual(self.wait_command(result["id"])["status"], "SUCCESS")
        (self.root / "example.sas").write_text("changed")
        result = self.app.launch({"action": "bundle-unpack"})
        self.assertEqual(self.wait_command(result["id"])["status"], "SUCCESS")
        self.assertIn("data demo", (self.root / "example.sas").read_text())
        self.assertTrue(list((self.root / "_codebase_backups").rglob("example.sas")))
        restored = ui.Workbench(self.root)
        self.assertEqual(len(restored.commands), 3)

    def test_saved_external_code_folders_and_bundle_round_trip(self):
        with tempfile.TemporaryDirectory(prefix="code folder ") as folder:
            code = Path(folder).resolve()
            (code / "job.sas").write_text("data external; run;\n")
            (self.root / "workspace.sas").write_text("data workspace; run;\n")
            settings = self.app.update_bundle_paths({"path": str(code)})
            self.assertEqual(settings["paths"], [str(code)])
            self.app.update_bundle_paths({"path": str(code)})
            self.assertEqual(len(self.app.bundle_settings()["paths"]), 1)
            for action in ("bundle-pack", "bundle-verify"):
                item = self.wait_command(self.app.launch({"action": action, "code_root": str(code)})["id"])
                self.assertEqual(item["status"], "SUCCESS")
                self.assertEqual(item["code_root"], str(code))
            bundle = (code / "codebase.sasbundle.txt").read_text()
            self.assertIn("job.sas", bundle)
            self.assertNotIn("workspace.sas", bundle)
            self.assertFalse((self.root / "codebase.sasbundle.txt").exists())
            (code / "job.sas").write_text("changed")
            item = self.wait_command(self.app.launch({"action": "bundle-unpack", "code_root": str(code)})["id"])
            self.assertEqual(item["status"], "SUCCESS")
            self.assertIn("data external", (code / "job.sas").read_text())
            self.assertTrue(list((code / "_codebase_backups").rglob("job.sas")))
            restored = ui.Workbench(self.root)
            self.assertEqual(restored.bundle_settings()["last"], str(code))
            self.assertEqual(restored.bundle_settings()["paths"], [str(code)])
            restored.update_bundle_paths({"operation": "remove", "path": str(code)})
            self.assertEqual(restored.bundle_settings()["paths"], [])
            self.assertTrue((code / "job.sas").exists())

    def test_invalid_code_folder_and_output_escape(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.app.update_bundle_paths({"path": "missing-folder"})
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                self.app.arguments({"action": "bundle-pack", "code_root": folder, "output": "../escape.txt"})

    def test_single_file_cli_accepts_root_without_ui_modules(self):
        code = self.root / "code"
        code.mkdir()
        (code / "standalone.sas").write_text("proc print; run;")
        for action in ("pack", "verify", "unpack"):
            result = subprocess.run([sys.executable, str(self.root / "pysas.py"), "bundle", action, "--root", str(code)], cwd=self.root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((code / "codebase.sasbundle.txt").exists())

    def test_bundle_target_rejects_escape(self):
        engine = worker.load_engine(self.root / "pysas.py")
        with self.assertRaises(ValueError):
            engine.bundle_target(self.root, "../elsewhere.sas")
        with self.assertRaises(ValueError):
            engine.bundle_target(self.root, str(self.root.parent / "elsewhere.sas"))

    def test_egp_round_trip(self):
        with zipfile.ZipFile(self.root / "demo.egp", "w") as z:
            z.writestr("Program1/code.sas", "proc print; run;")
            z.writestr("project.xml", "<Project/>")
        for action in ("egp-inspect", "egp-extract"):
            item = self.wait_command(self.app.launch({"action": action, "project": "demo.egp"})["id"])
            self.assertEqual(item["status"], "SUCCESS")
        extracted = list(self.root.rglob(".pysas_egp_manifest.json"))[0].parent
        item = self.wait_command(self.app.launch({"action": "egp-pack", "source": str(extracted), "template": "demo.egp", "output": "updated.egp"})["id"])
        self.assertEqual(item["status"], "SUCCESS")
        with zipfile.ZipFile(self.root / "updated.egp") as z:
            self.assertEqual(z.read("project.xml"), b"<Project/>")

    def test_path_escape_and_command_injection_rejected(self):
        for value in ("../outside.txt", str(self.root.parent / "outside.txt")):
            with self.assertRaises(ValueError):
                self.app.arguments({"action": "bundle-pack", "output": value})
            with self.assertRaises(ValueError):
                self.app.preview(value)
        with self.assertRaises(ValueError):
            self.app.arguments({"action": "shell", "command": "echo unsafe"})
        with self.assertRaises(ValueError):
            self.app.arguments({"action": "bundle-pack", "output": "pysas.py"})
        _, args = self.app.arguments({"action": "bundle-pack", "output": "name & literal.txt"})
        self.assertEqual(args[-1], str((self.root / "name & literal.txt").resolve()))

    def test_monitor_preserves_elapsed_and_status(self):
        item = {"id": "test", "tasks": {}}
        self.app.event(item, {"event": "plan", "tasks": [{"task_id": "A", "program": "prepare", "depends_on": [], "skip": False}]})
        self.app.event(item, {"event": "start", "key": "A", "name": "prepare", "kind": "task", "time": 100})
        self.app.event(item, {"event": "location", "key": "A", "path": self.root / "runs/test/tasks/A"})
        self.assertEqual(item["tasks"]["A"]["status"], "RUNNING")
        self.assertEqual(item["tasks"]["A"]["started"], 100)
        self.app.event(item, {"event": "finish", "key": "A", "status": "FAILED", "time": 107})
        self.assertEqual(item["tasks"]["A"]["elapsed"], 7)
        self.app.event(item, {"event": "summary", "path": self.root / "runs/test", "tasks": [{"task_id": "A", "program": "prepare", "status": "FAILED", "elapsed": 7}, {"task_id": "B", "program": "next", "status": "BLOCKED_DEPENDENCY", "elapsed": 0}]})
        self.assertEqual(item["tasks"]["B"]["status"], "BLOCKED_DEPENDENCY")

    def test_file_events_are_independent_of_partial_console_lines(self):
        from types import SimpleNamespace
        item = {"id": "mixed", "action": "run", "started": time.time(), "status": "RUNNING", "tasks": {}}
        self.app.commands["mixed"] = item
        event = {"event": "start", "key": "A", "name": "a.sas", "time": time.time()}
        finished = {"event": "finish", "key": "A", "name": "a.sas", "status": "SUCCESS", "elapsed": 2, "time": time.time()}
        events = self.app.storage / "mixed.events.jsonl"
        events.write_text(json.dumps(event) + "\n" + json.dumps(finished) + "\n", encoding="utf-8")
        console = self.app.storage / "mixed.txt"
        console.write_text("console text without newline", encoding="utf-8")
        process = SimpleNamespace(stdin=io.StringIO(), wait=lambda: 0, poll=lambda: 0)
        self.app.monitor_worker("mixed", process, events)
        self.assertEqual(item["tasks"]["A"]["status"], "SUCCESS")
        self.assertEqual(item["tasks"]["A"]["elapsed"], 2)
        self.assertEqual(console.read_text(), "console text without newline")

    def test_historical_status_and_duration(self):
        complete = self.root / "runner/runs/20260914__done"
        complete.mkdir(parents=True)
        (complete / "status.txt").write_text("status=SAS_ERROR\nsource=check.sas\nstarted=2026-09-14T12:00:00\nelapsed_seconds=65.4\n")
        unknown = self.root / "runner/runs/20260914__unfinished"
        unknown.mkdir()
        old_schedule = self.root / "runs/old__schedule"
        old_schedule.mkdir(parents=True)
        (old_schedule / "run_summary.csv").write_text("task_id,program,status,elapsed,depends_on,message\nA,one,SUCCESS,10,,\nB,two,SUCCESS,10,,\n")
        rows = {r["name"]: r for r in self.app.history()}
        self.assertEqual(rows["check.sas"]["elapsed"], 65.4)
        self.assertEqual(rows["check.sas"]["status"], "SAS_ERROR")
        self.assertEqual(rows[unknown.name]["status"], "UNKNOWN")
        self.assertIsNone(rows[old_schedule.name]["elapsed"])
        self.assertEqual(rows[old_schedule.name]["status"], "SUCCESS")

    def test_interrupted_commands_are_unknown_on_restart(self):
        item = {"id": "stale", "action": "watch", "status": "RUNNING", "tasks": {"file": {"status": "RUNNING"}}}
        self.app.save(item)
        restored = ui.Workbench(self.root)
        self.assertEqual(restored.commands["stale"]["status"], "UNKNOWN")
        self.assertEqual(restored.commands["stale"]["tasks"]["file"]["status"], "UNKNOWN")

    def test_configured_inputs_are_listed_and_passed_to_engine(self):
        with tempfile.TemporaryDirectory() as folder:
            inputs = Path(folder).resolve()
            (inputs / 'job.sas').write_text('run;')
            (inputs / 'project.egp').write_text('fake')
            (inputs / '_init.sas').write_text('init;')
            self.app.update_folders({'inputs': str(inputs), 'init': str(inputs)})
            self.assertIn(str(inputs / 'job.sas'), self.app.inventory())
            from types import SimpleNamespace
            with patch('pysas_ui.os', SimpleNamespace(name='nt')):
                _, args = self.app.arguments({'action': 'run', 'program': str(inputs / 'job.sas')})
            self.assertEqual(args[args.index('--init-dir') + 1], str(inputs))
            self.assertEqual(args[args.index('--template') + 1], str(inputs / 'project.egp'))
            self.assertEqual(ui.Workbench(self.root).folders()['inputs'], str(inputs))
            self.app.commands['active'] = {'status': 'RUNNING'}
            with self.assertRaisesRegex(ValueError, 'active commands'):
                self.app.update_folders({'inputs': str(self.root)})

    def test_native_execution_gate(self):
        if os.name != "nt":
            with self.assertRaisesRegex(ValueError, "Windows"):
                self.app.arguments({"action": "watch"})
        from types import SimpleNamespace
        with patch("pysas_ui.os", SimpleNamespace(name="nt")):
            with self.assertRaisesRegex(ValueError, "Workers"):
                self.app.arguments({"action": "watch", "workers": 0.2})

    def test_excel_preview_is_bounded(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl is optional locally")
        book = openpyxl.Workbook()
        for n in range(150):
            book.active.append([n, "value"])
        book.save(self.root / "tables.xlsx")
        result = self.app.preview("tables.xlsx")
        self.assertEqual(len(result["sheets"][0]["rows"]), 101)


class ObservationTests(unittest.TestCase):
    def test_adapter_calls_original_functions_and_reports_events(self):
        engine = worker.load_engine(ROOT / "pysas.py")
        calls = []
        def fake_job(source, *args, **kwargs):
            calls.append((source, args, kwargs))
            engine.execute_eg("RUNFILE", Path("p.egp"), source, "test", 0, 0, Path("run"), False)
            return {"name": source.name, "status": "SUCCESS", "elapsed": 2.5, "run_dir": Path("run")}
        engine.run_job = fake_job
        engine.execute_eg = lambda *a: (0, "done")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            worker.observe(engine)
            result = engine.run_job(Path("hello.sas"), "sentinel", tables=True)
        self.assertEqual(calls, [(Path("hello.sas"), ("sentinel",), {"tables": True})])
        self.assertEqual(result["elapsed"], 2.5)
        events = [json.loads(line[len(worker.PREFIX):]) for line in buffer.getvalue().splitlines()]
        self.assertEqual([e["event"] for e in events], ["start", "location", "finish"])
        self.assertEqual(events[-1]["elapsed"], 2.5)

    def test_exceptions_are_observed_then_reraised(self):
        engine = worker.load_engine(ROOT / "pysas.py")
        def fail(*args, **kwargs):
            raise RuntimeError("automation failed")
        engine.run_job = fail
        with contextlib.redirect_stdout(io.StringIO()) as output:
            worker.observe(engine)
            with self.assertRaisesRegex(RuntimeError, "automation failed"):
                engine.run_job(Path("bad.sas"))
        self.assertIn('"status": "FAILED"', output.getvalue())

    def test_watcher_stop_allows_running_job_to_finish(self):
        # Exercise the real adapter control pipe on Windows and POSIX without SAS.
        with tempfile.TemporaryDirectory() as folder:
            engine = Path(folder) / "fake_engine.py"
            engine.write_text("""import concurrent.futures, time
from pathlib import Path
def execute_eg(*a): return (0, '')
def run_job(source):
    time.sleep(0.6)
    return dict(name=source.name, status='SUCCESS', elapsed=0.6, run_dir=Path('run'))
def scheduler_task(*a): pass
def load_schedule(*a): return []
def write_summary(*a): pass
def main(args):
    executor = concurrent.futures.ThreadPoolExecutor(1)
    executor.submit(run_job, Path('test.sas'))
    try:
        while True: time.sleep(0.05)
    except KeyboardInterrupt:
        print('Watcher stopped; waiting for jobs.', flush=True)
        return 130
    finally: executor.shutdown(wait=True)
""")
            process = subprocess.Popen([sys.executable, "-u", str(ROOT / "ui_worker.py"), str(engine), "runner", "watch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
            try:
                while True:
                    first = process.stdout.readline()
                    if not first or '"event": "start"' in first:
                        break
                self.assertIn('"event": "start"', first)
                output, errors = process.communicate("stop\n", timeout=10)
                self.assertEqual(process.returncode, 130, errors)
                self.assertIn('"status": "SUCCESS"', output)
                self.assertIn("waiting for jobs", output)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copy2(ROOT / "pysas.py", self.root / "pysas.py")
        self.server = ui.make_server(self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        connection.close()
        return result

    def test_parameter_editor_http_save_load_and_legacy_import(self):
        headers = {'X-PySAS-Token': self.server.token}
        status, body, _ = self.request('POST', '/api/parameters/save', json.dumps({'name':'_cases.sas','text':'%let ids=1;'}), headers)
        self.assertEqual(status, 200, body)
        status, body, _ = self.request('GET', '/api/parameters?name=_cases.sas')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['text'], '%let ids=1;')
        status, body, _ = self.request('POST', '/api/parameters/import?name=cases.sas', '%let city=café;'.encode('cp1252'), headers)
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)['text'], '%let city=café;')
        self.assertFalse((self.server.app.storage/'parameters/cases.sas').exists())
        status, _, _ = self.request('POST', '/api/parameters/save', '{}')
        self.assertEqual(status, 403)
        status, _, _ = self.request('POST', '/api/parameters/import?name=bad.py', b'code', headers)
        self.assertEqual(status, 400)

    def test_copy_reads_complete_log_and_respects_text_encodings_and_path_limits(self):
        folder = self.root/'runs/copy'; folder.mkdir(parents=True)
        text = 'FIRST LINE café\n' + 'NOTE: line of log output\n'*30000 + 'LAST LINE\n'
        for encoding in ('utf-8', 'cp1252', 'utf-16'):
            (folder/'full.log').write_bytes(text.encode(encoding))
            status, body, _ = self.request('GET', '/api/preview?path=runs/copy/full.log')
            self.assertEqual(status, 200)
            self.assertNotIn('FIRST LINE', json.loads(body)['text'])
            status, body, _ = self.request('GET', '/api/file-text?path=runs/copy/full.log')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)['text'], text)
        (folder/'job.sas').write_text('%let cases=123;')
        status, body, _ = self.request('GET', '/api/file-text?path=runs/copy/job.sas')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['text'], '%let cases=123;')
        for path in ('../outside.log', 'runs/copy/results.xlsx', 'runs/copy/missing.log'):
            self.assertEqual(self.request('GET', '/api/file-text?path='+path)[0], 400)
        self.assertEqual(self.request('GET', '/api/file-text?path=runs/copy/full.log', headers={'Origin':'https://evil.example'})[0], 403)

    def test_server_catalog_http_and_snapshot_download(self):
        path = self.server.app.storage/'artifacts/catalog/server-catalog.json'
        path.parent.mkdir(parents=True)
        payload = dict(libraries=[], tables=[], label='Test connection', captured=1)
        ui.atomic_json(path, payload)
        self.server.app.commands['catalog'] = dict(id='catalog', action='server-refresh', status='SUCCESS', started=1, tasks={}, server=dict(label='Test connection', snapshot=self.server.app.relative(path)))
        status, body, _ = self.request('GET', '/api/server-catalog?id=catalog')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), payload)
        status, body, _ = self.request('GET', '/api/download?path=.pysas-ui/artifacts/catalog/server-catalog.json')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), payload)
        self.assertEqual(self.request('GET', '/api/server-catalog?id=unknown')[0], 400)

    def test_saved_data_http_roundtrip_and_folder_zip(self):
        folder = self.root / 'runs' / 'old'
        folder.mkdir(parents=True)
        (folder / 'schedule.log').write_text('full log')
        status, archive, headers = self.request('GET', '/api/backup')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'application/zip')
        status, body, _ = self.request('POST', '/api/restore', archive)
        self.assertEqual(status, 403)
        status, body, _ = self.request('POST', '/api/restore', archive, {'X-PySAS-Token': self.server.token})
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)['runs'], 1)
        status, body, _ = self.request('GET', '/api/run-zip?path=runs/old')
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            self.assertEqual(z.read('old/schedule.log'), b'full log')
        status, body, _ = self.request('GET', '/api/run-zip?path=.pysas-ui')
        self.assertEqual(status, 400)
        status, body, _ = self.request('POST', '/api/estimate', json.dumps({'program': 'new.sas'}), {'X-PySAS-Token': self.server.token})
        self.assertEqual(status, 200, body)
        self.assertIsNone(json.loads(body)['seconds'])

    def test_combined_schedule_log_download_is_complete(self):
        folder = self.root/'runs'/'combined'; folder.mkdir(parents=True)
        body = ('NOTE: schedule log\n'*30000 + 'LAST LINE café\n').encode('utf-8')
        (folder/'schedule.log').write_bytes(body)
        status, downloaded, headers = self.request('GET', '/api/download?path=runs/combined/schedule.log')
        self.assertEqual(status, 200)
        self.assertEqual(downloaded, body)
        self.assertIn('schedule.log', headers['Content-Disposition'])

    def test_bundle_download_retains_each_completed_output(self):
        with tempfile.TemporaryDirectory() as directory:
            code_root = Path(directory)
            (code_root / 'job.sas').write_text('data first; run;')
            headers = {'X-PySAS-Token': self.server.token, 'Content-Type': 'application/json'}
            status, body, _ = self.request('POST', '/api/launch', json.dumps({'action':'bundle-pack','code_root':str(code_root)}), headers)
            self.assertEqual(status, 200, body)
            identifier = json.loads(body)['id']
            deadline = time.monotonic() + 10
            while identifier in self.server.app.processes and time.monotonic() < deadline:
                time.sleep(.05)
            item = self.server.app.commands[identifier]
            self.assertEqual(item['status'], 'SUCCESS', item)
            self.assertIn('download', item)
            original = (code_root / 'codebase.sasbundle.txt').read_bytes()
            (code_root / 'codebase.sasbundle.txt').write_text('later bundle')
            status, body, headers = self.request('GET', '/api/download?command=' + identifier)
            self.assertEqual(status, 200)
            self.assertEqual(body, original)
            self.assertIn('attachment', headers['Content-Disposition'])
            self.assertEqual(self.request('GET','/api/download?command=missing')[0],400)

    def test_second_launcher_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "already running"):
            ui.make_server(self.root)

    def test_serves_ui_assets_and_state(self):
        for path in ("/", "/app.js", "/style.css", "/icon.svg", "/api/state"):
            status, body, headers = self.request("GET", path)
            self.assertEqual(status, 200, path)
            self.assertIn("Content-Security-Policy", headers)
        _, body, _ = self.request("GET", "/api/state")
        self.assertIn("token", json.loads(body))

    def test_http_upload_and_folder_settings(self):
        headers = {'X-PySAS-Token': self.server.token, 'Content-Type': 'application/json'}
        status, body, _ = self.request('POST', '/api/folders', json.dumps({'inputs': str(self.root), 'init': str(self.root), 'inbox': str(self.root / 'runner/inbox')}), headers)
        self.assertEqual(status, 200, body)
        status, body, _ = self.request('POST', '/api/upload?target=init&name=_setup.sas', b'init;', headers)
        self.assertEqual(status, 200, body)
        self.assertEqual((self.root / '_setup.sas').read_bytes(), b'init;')
        self.assertEqual(self.request('POST', '/api/upload?target=init&name=job.sas', b'run;', headers)[0], 400)
        self.assertEqual(self.request('POST', '/api/upload?target=inputs&name=secret.sas', b'run;')[0], 403)
        self.assertEqual(self.request('POST', '/api/upload?target=inbox&name=job.sas', b'run;', headers)[0], 200)
        deadline = time.monotonic() + 3
        while not self.server.app.state()['queued'] and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertEqual(self.server.app.state()['queued'], ['job.sas'])
        self.assertEqual(self.request('POST', '/api/upload?target=inbox&name=job.sas', b'edit;', headers)[0], 400)
        self.assertEqual((self.root / 'runner/inbox/job.sas').read_bytes(), b'run;')

    def test_cross_origin_host_and_missing_token_rejected(self):
        self.assertEqual(self.request("GET", "/api/state", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/state", headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/launch", body='{"action":"bundle-pack"}')[0], 403)
        self.assertEqual(self.request("GET", "/api/preview?path=../outside.txt")[0], 400)


class PackagingTests(unittest.TestCase):
    def test_zip_contains_current_engine_and_only_release_files(self):
        from tools.package_release import build, FILES
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            archive = build(folder)
            with zipfile.ZipFile(archive) as z:
                self.assertEqual(set(z.namelist()), {"PySAS-Workbench/" + name for name in FILES})
                self.assertEqual(z.read("PySAS-Workbench/pysas.py"), (ROOT / "pysas.py").read_bytes())
                self.assertFalse(any(".pysas-ui" in name for name in z.namelist()))
            checksum = (Path(folder) / "SHA256SUMS.txt").read_text().split()[0]
            self.assertEqual(checksum, hashlib.sha256(archive.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
