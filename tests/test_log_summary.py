from pathlib import Path
import tempfile
import unittest
from ui_logs import LogIndex


class LogSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'sas.log'
        self.index=LogIndex()

    def tearDown(self): self.temp.cleanup()

    def test_full_file_numbered_diagnostics_and_echoed_source(self):
        content='NOTE: Errors mentioned in a note are not diagnostics.\n42 %put ERROR: example;\nERROR_COUNT=0\n'
        content+='ERROR 180-322: Statement is not valid.\n'
        content+='NOTE: padding\n'*12000
        content+='  WARNING: Variable missing.\n'
        self.path.write_text(content,encoding='utf-8')
        result=self.index.summary(self.path)
        self.assertEqual(result['counts'],dict(error=1,warning=1))
        self.assertEqual([i['line'] for i in result['issues']],[4,12005])
        self.assertEqual(result['first'],dict(error=0,warning=1))
        selected=self.index.summary(self.path,issue=0,revision=result['revision'])['context']
        self.assertEqual(selected['selected_line'],4)
        self.assertIn('ERROR 180-322:', selected['lines'][3])
        self.assertGreater(len(selected['lines']),4)

    def test_all_issues_are_available_in_pages_and_filtered_in_original_order(self):
        self.path.write_text(''.join(f'ERROR: issue {i}\nWARNING: check {i}\n' for i in range(90)))
        first=self.index.summary(self.path,kind='error')
        second=self.index.summary(self.path,kind='error',offset=50)
        self.assertEqual(first['total'],90)
        self.assertEqual(len(first['issues'])+len(second['issues']),90)
        self.assertEqual(second['issues'][0]['line'],101)
        self.assertEqual(self.index.summary(self.path,kind='warning')['issues'][0]['line'],2)

    def test_utf16_and_ansi_context_uses_same_decoder_and_line_numbers(self):
        for encoding in ['utf-16','utf-16-be','cp1252','utf-8-sig']:
            with self.subTest(encoding=encoding):
                self.path.write_bytes(('NOTE: café\r\n'*16+'WARNING: café\r\ncontinuation\r\n').encode(encoding))
                result=self.index.summary(self.path)
                self.assertEqual(result['counts']['warning'],1)
                selected=self.index.summary(self.path,issue=0,revision=result['revision'])['context']
                self.assertEqual(selected['selected_line'],17)
                self.assertIn('WARNING: café',selected['lines'])
                self.assertIn('continuation',selected['lines'])

    def test_cache_reuse_append_and_stale_context_guard(self):
        self.path.write_text('ERROR: first\n')
        cached=self.index.scan(self.path)
        self.assertIs(cached,self.index.scan(self.path))
        with self.path.open('a') as stream:stream.write('WARNING: later\n')
        result=self.index.summary(self.path,issue=0,revision=cached['revision'])
        self.assertEqual(result['counts'],dict(error=1,warning=1))
        self.assertIn('context_error',result)
        self.assertNotIn('context',result)
        self.path.write_text('NOTE: replacement\n')
        self.assertEqual(self.index.summary(self.path)['total'],0)

    def test_empty_invalid_kind_and_invalid_issue(self):
        self.path.touch()
        result=self.index.summary(self.path)
        self.assertEqual(result['first'],dict(error=None,warning=None))
        self.assertEqual(result['lines'],0)
        with self.assertRaises(ValueError):self.index.summary(self.path,kind='bad')
        with self.assertRaises(ValueError):self.index.summary(self.path,issue=-1,revision=result['revision'])
