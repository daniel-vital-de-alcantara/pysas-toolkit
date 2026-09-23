"""Optional SAS parameter files, stored separately from shared initialization."""
from pathlib import Path
import hashlib
import json
import re
import uuid
from pysas import text_encoding

PARAMETER_LIMIT = 128 * 1024


def parameter_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[\w .-]+\.sas', value, re.IGNORECASE) or value.startswith('.') or value.endswith((' ', '.')) or len(value) > 100:
        raise ValueError('Use a plain SAS filename, such as _cases.sas (up to 100 characters).')
    if re.match(r'(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', value):
        raise ValueError('Choose another parameter filename.')
    return value


def parameter_text(value):
    if not isinstance(value, str) or '\x00' in value or len(value.encode('utf-8')) > PARAMETER_LIMIT:
        raise ValueError('Parameter code must be text, up to 128 KB.')
    return value.replace('\r\n', '\n').replace('\r', '\n').lstrip('\ufeff')


def settings(storage):
    try:
        value = json.loads((storage / 'parameters-settings.json').read_text(encoding='utf-8'))
        return {'last': parameter_name(value['last']) if value.get('last') else '', 'enabled': value.get('enabled') is True}
    except (OSError, ValueError, TypeError, KeyError):
        return {'last': '', 'enabled': False}


def list_parameters(storage):
    folder = storage / 'parameters'
    return sorted(p.name for p in folder.glob('*') if p.is_file() and not p.is_symlink() and p.suffix.lower() == '.sas')


def parameter_path(storage, name):
    folder = storage / 'parameters'
    if folder.is_symlink():
        raise ValueError('The saved parameters folder must be inside the workbench.')
    target = folder / parameter_name(name)
    for existing in folder.glob('*'):
        if existing.name.casefold() == target.name.casefold():
            target = existing
            break
    if target.is_symlink():
        raise ValueError('Linked parameter files cannot be edited.')
    return target


def load_parameters(storage, name):
    path = parameter_path(storage, name)
    with path.open('rb') as f:
        raw = f.read(PARAMETER_LIMIT + 1)
    if len(raw) > PARAMETER_LIMIT:
        raise ValueError('Parameter file exceeds 128 KB.')
    text = parameter_text(raw.decode(text_encoding(raw)))
    return {'name': path.name, 'text': text, 'revision': hashlib.sha256(raw).hexdigest()}


def save_parameters(storage, data):
    path = parameter_path(storage, data.get('name'))
    text = parameter_text(data.get('text'))
    # Optimistic version check protects another window's edits.
    if path.exists():
        if data.get('revision') != load_parameters(storage, path.name)['revision']:
            raise ValueError('This saved file already exists or changed in another window. Reload it, or save under another name.')
    path.parent.mkdir(exist_ok=True)
    temp = path.with_name('.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(text, encoding='utf-8')
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return load_parameters(storage, path.name)
