"""Read-only, full-file SAS diagnostic index with paginated results and context."""
from collections import OrderedDict, deque
import re
import threading
from pysas import text_encoding

# Match diagnostics, not echoed source (e.g. 42 %put ERROR: ...), ERROR_COUNT,
# WARNING labels inside code, or SAS NOTE messages mentioning an error.
DIAGNOSTIC = re.compile(r'^\s*(ERROR|WARNING)(?:\s+\d+(?:-\d+)?)?\s*:', re.I)
PAGE_SIZE = 50


class LogIndex:
    def __init__(self):
        self.cache = OrderedDict()
        self.lock = threading.Lock()

    @staticmethod
    def revision(path):
        stat = path.stat()
        return f'{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}'

    def scan(self, path):
        revision = self.revision(path)
        with self.lock:
            found = self.cache.get(str(path))
            if found and found['revision'] == revision:
                self.cache.move_to_end(str(path))
                return found
        with path.open('rb') as stream:
            encoding = text_encoding(stream.read(4096))
        issues, before = [], deque(maxlen=12)
        line_number = 0
        with path.open(encoding=encoding, errors='replace', newline=None) as stream:
            while True:
                position = stream.tell()
                line = stream.readline()
                if not line: break
                line_number += 1
                before.append((position, line_number))
                match = DIAGNOSTIC.match(line)
                if match:
                    issues.append(dict(index=len(issues), severity=match[1].lower(), line=line_number,
                                       message=line.strip()[:2000], context=before[0]))
        result = dict(revision=revision, issues=issues, lines=line_number, encoding=encoding,
                      changed=self.revision(path) != revision)
        if not result['changed']:
            with self.lock:
                self.cache[str(path)] = result
                while len(self.cache) > 4: self.cache.popitem(last=False)
        return result

    def summary(self, path, kind='all', offset=0, issue=None, revision=''):
        if path.suffix.lower() != '.log': raise ValueError('Choose a SAS .log file.')
        if kind not in {'all', 'error', 'warning'}: raise ValueError('Choose errors, warnings, or all issues.')
        offset = max(0, int(offset))
        data = self.scan(path)
        issues = data['issues']
        matches = [i for i in issues if kind == 'all' or i['severity'] == kind]
        offset = min(offset, max(0, ((len(matches)-1)//PAGE_SIZE)*PAGE_SIZE))
        counts = {level: sum(i['severity'] == level for i in issues) for level in ('error', 'warning')}
        result = dict(revision=data['revision'], counts=counts, total=len(matches), offset=offset,
                      page_size=PAGE_SIZE, lines=data['lines'], changed=data['changed'],
                      first={level: next((i['index'] for i in issues if i['severity'] == level), None) for level in counts},
                      issues=[{k:v for k,v in i.items() if k != 'context'} for i in matches[offset:offset+PAGE_SIZE]])
        if issue is not None:
            if revision != data['revision'] or data['changed']:
                result['context_error'] = 'The log changed. Select an issue again to view its current context.'
            else:
                number = int(issue)
                if not 0 <= number < len(issues): raise ValueError('This log issue is no longer available.')
                selected = issues[number]
                position, start = selected['context']
                rows = []
                with path.open(encoding=data['encoding'], errors='replace', newline=None) as stream:
                    stream.seek(position)
                    for _ in range(selected['line']-start+26):
                        line = stream.readline()
                        if not line: break
                        rows.append(line.rstrip('\r\n')[:8000])
                if self.revision(path) != data['revision']:
                    result['context_error'] = 'The log changed. Select an issue again to view its current context.'
                else:
                    result['context'] = dict(start=start, selected_line=selected['line'], lines=rows)
        return result
