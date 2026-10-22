"""Inspect/extract SAS programs and process flows from EGP archives, without SAS.

Standard library only. Run: python egp_extract.py project.egp --output extracted
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import stat
import tempfile
from xml.etree import ElementTree as ET
import zipfile

def egp_archive_path(value: str) -> PurePosixPath:
    value = value.replace("\\", "/")
    path = PurePosixPath(value)
    if (not value or value.startswith("/") or PureWindowsPath(value).drive or
            ".." in path.parts or not path.parts or any(ord(c) < 32 for c in value)):
        raise ValueError("Unsafe path in EGP archive or manifest: " + repr(value))
    return path


def egp_component(value: str, fallback="Unnamed", limit=80) -> str:
    # Preserve readable labels, spaces and Unicode, while producing Windows filenames.
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value)).strip().rstrip(". ")
    if value in {"", ".", ".."}: value = fallback
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", value): value = "_" + value
    return value[:limit].rstrip(". ") or fallback


def egp_unique(value: str, used: set[str], suffix="") -> str:
    original = value
    number = 0
    while (value + suffix).casefold() in used:
        number += 1
        value = f"{original} ({number})"
    result = value + suffix
    used.add(result.casefold())
    return result


def egp_project_index(zf: zipfile.ZipFile, members: dict[str, zipfile.ZipInfo]):
    """Resolve classic PFD membership and newer container/parent relationships."""
    warnings = []
    xml = next((info for key, info in members.items() if key.casefold() == "project.xml"), None)
    if xml is None:
        return {}, {}, ["project.xml is missing; archive names and Unknown flows were used."]
    if xml.file_size > 16 * 1024**2: raise ValueError("EGP project.xml exceeds the 16 MB metadata limit.")
    raw = zf.read(xml)
    # Reject external/entity definitions; ordinary EG XML has no DTD.
    normalized_xml = raw.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in normalized_xml or b"<!ENTITY" in normalized_xml:
        raise ValueError("EGP project.xml contains unsupported entity definitions.")
    try:
        root = ET.fromstring(raw)  # XML declarations/BOMs select UTF-8/UTF-16 correctly.
    except ET.ParseError:
        return {}, {}, ["project.xml could not be parsed; every embedded SAS file is still retained."]
    local = lambda node: node.tag.rsplit("}", 1)[-1].casefold()
    nodes = [node for node in root.iter() if local(node) == "element" and node.get("Type")]
    def text(node, names):
        # Prefer the element's own metadata over IDs inside PFD child processes.
        own = next((child for child in node if local(child) == "element" and not child.get("Type")), node)
        for name in names:
            for child in own.iter():
                if local(child) == name.casefold():
                    value = (child.text or child.get("ID") or "").strip()
                    if value: return value
        return ""
    flows, parents, programs, membership = {}, {}, {}, {}
    for node in nodes:
        kind = node.get("Type", "").rsplit(".", 1)[-1].casefold()
        identifier = text(node, ["ID"])
        label = text(node, ["Label", "Name"])
        if not identifier: continue
        parents[identifier] = text(node, ["Container", "ContainerID", "ParentID", "Parent", "OwnerID"])
        if kind in {"pfd", "processflow", "container"}:
            flows[identifier] = label or "Unnamed flow"
            if kind == "pfd":
                for process in node.iter():
                    if local(process) == "process":
                        reference = next(((child.text or "").strip() for child in process.iter() if local(child) == "id" and child.text), "")
                        if reference: membership.setdefault(reference, identifier)
        elif kind == "codetask":
            if identifier in programs: warnings.append("Duplicate program ID in project.xml: " + identifier)
            else: programs[identifier] = dict(label=label or "Unnamed_Code", parent=parents[identifier])
    for identifier, program in programs.items():
        parent = program["parent"]
        visited = set()
        while parent and parent not in visited:
            visited.add(parent)
            if parent in flows:
                program["flow"] = parent
                break
            parent = parents.get(parent, "")
        if not program.get("flow") and identifier in membership:
            program["flow"] = membership[identifier]
    return programs, flows, warnings


def _members(archive):
    infos = archive.infolist()
    if len(infos) > 20000 or sum(i.file_size for i in infos) > 2 * 1024**3:
        raise ValueError('EGP exceeds the 20,000 entry / 2 GB expanded limit.')
    members, seen = {}, set()
    for info in infos:
        key = str(egp_archive_path(info.orig_filename))
        if key.casefold() in seen: raise ValueError('Duplicate/colliding EGP path: ' + key)
        seen.add(key.casefold())
        if info.flag_bits & 1 or stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError('Encrypted/symbolic EGP entries are unsupported.')
        if info.file_size > 256 * 1024**2: raise ValueError('EGP member exceeds 256 MB.')
        if not info.is_dir() and not info.filename.endswith('\\'): members[key] = info
    return members


def inspect_project(path):
    """Return ordered flow/program metadata, including missing external sources."""
    with zipfile.ZipFile(path) as archive:
        members = _members(archive)
        programs, flows, warnings = egp_project_index(archive, members)
        sas = {key.casefold(): info for key, info in members.items() if key.lower().endswith('.sas')}
        counts = {}
        for program in programs.values():
            key = program['label'].casefold(); counts[key] = counts.get(key, 0) + 1
        result, used = [], set()
        for identifier, program in programs.items():
            info = sas.get((identifier.replace('\\', '/').rstrip('/') + '/code.sas').casefold())
            if info: used.add(info.filename)
            else: warnings.append('Source is linked externally or not embedded: ' + program['label'])
            result.append(dict(id=identifier, name=program['label'], flow_id=program.get('flow'),
                               flow=flows.get(program.get('flow'), 'Unassigned'), member=info.filename if info else None,
                               bytes=info.file_size if info else None, duplicate=counts[program['label'].casefold()] > 1))
        for key, info in sas.items():
            if info.filename in used: continue
            relative = egp_archive_path(info.filename)
            name = relative.parts[-2] if relative.stem.lower() == 'code' and len(relative.parts) > 1 else relative.stem
            result.append(dict(id='member:' + str(relative), name=name, flow_id=None, flow='Unassigned',
                               member=info.filename, bytes=info.file_size, duplicate=False))
            warnings.append('Unmapped embedded source retained: ' + info.filename)
    return dict(programs=result, flows=[dict(id=identifier, name=name) for identifier, name in flows.items()],
                warnings=warnings, connection_valid=bool(programs))


def read_program(path, program_id, *, limit=256 * 1024**2):
    """Read a catalog program by stable ID; never follow linked/external paths."""
    catalog = inspect_project(path)
    program = next((p for p in catalog['programs'] if p['id'] == program_id), None)
    if not program: raise ValueError('This program is not in the selected EGP.')
    if not program['member']: raise ValueError('This program is linked externally. Choose its SAS file from your PC.')
    if program['bytes'] > limit: raise ValueError('Selected program exceeds the source size limit.')
    with zipfile.ZipFile(path) as archive:
        return program, archive.read(program['member'])


def extract_project(path, output, program_ids=None):
    """Atomically export original SAS bytes in flat and process-flow folders."""
    path, output = Path(path).resolve(), Path(output).resolve()
    if output.exists(): raise FileExistsError('Choose a new output folder; existing files are preserved: ' + str(output))
    catalog = inspect_project(path)
    requested = set(program_ids) if program_ids is not None else None
    if requested is not None and requested - {p['id'] for p in catalog['programs']}:
        raise ValueError('One or more selected program IDs are not in this EGP.')
    selected = [p for p in catalog['programs'] if p['member'] and (requested is None or p['id'] in requested)]
    if not selected: raise ValueError('No selected embedded SAS source is available.')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.egp-extract-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'project'; stage.mkdir()
        auxiliary = stage / '02 Other files'; auxiliary.mkdir()
        shutil.copy2(path, auxiliary / 'original-egp.zip')
        flat_used, flow_used, group_used, flow_names, records = set(), set(), {}, {}, []
        with zipfile.ZipFile(path) as archive:
            members = _members(archive)
            xml = next((i for k, i in members.items() if k.casefold() == 'project.xml'), None)
            if xml: (auxiliary / 'project.xml').write_bytes(archive.read(xml))
            for program in selected:
                flow_id = program['flow_id'] or 'unassigned'
                if flow_id not in flow_names:
                    flow_names[flow_id] = egp_unique(egp_component(program['flow'], limit=60), flow_used)
                folder = flow_names[flow_id]
                name = program['name'][:-4] if program['name'].lower().endswith('.sas') else program['name']
                limit = min(80, 220 - len(str(output / '03. By process flow' / folder))) if os.name == 'nt' else 80
                if limit < 8: raise ValueError('Choose a shorter output path for extraction.')
                stem = egp_component(name, 'Program', limit)
                flat = Path('01 SAS project files') / egp_unique(stem, flat_used, '.sas')
                grouped = Path('03. By process flow') / folder / egp_unique(stem, group_used.setdefault(folder, set()), '.sas')
                raw = archive.read(program['member'])
                for relative in (flat, grouped):
                    target = stage / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
                records.append(dict(program, path=flat.as_posix(), by_flow=grouped.as_posix(), sha256=hashlib.sha256(raw).hexdigest()))
        saved = dict(format='pysas-egp-programs-1', source=str(path), programs=records, warnings=catalog['warnings'])
        (stage / 'catalog.json').write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding='utf-8')
        if output.exists(): raise FileExistsError('Output appeared during extraction; no files were replaced.')
        stage.rename(output)
    return dict(path=str(output), programs=records, warnings=catalog['warnings'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--output', type=Path, help='New folder for flat and process-flow SAS exports')
    parser.add_argument('--program', action='append', help='Stable program ID to extract; repeat to select several')
    parser.add_argument('--json', action='store_true', help='Print machine-readable catalog/result')
    args = parser.parse_args(argv)
    try:
        result = extract_project(args.project, args.output, args.program) if args.output else inspect_project(args.project)
        if args.json: print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            for program in result['programs']:
                print(program['flow'] + ' / ' + program['name'] + ' [' + program['id'] + ']' + ('' if program['member'] else ' (external source)'))
            for warning in result['warnings']: print('WARNING: ' + warning)
            if args.output: print('Saved: ' + result['path'])
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        parser.exit(1, str(exc) + '\n')
    return 0


if __name__ == '__main__': raise SystemExit(main())
