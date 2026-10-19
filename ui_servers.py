"""Saved SAS library catalogs transported through the existing EG log export.

Only metadata is queried. No shared filesystem, table download or COM polling.
The short ASCII records survive SAS log encodings and line-width limits; text
values are UTF-8 hex chunks, decoded only after the complete record is received.
"""
from __future__ import annotations

import copy
import math
import re
from pathlib import Path
from pysas import read_text


def library_filter(value):
    names = list(dict.fromkeys(re.split(r"[,\s]+", str(value).strip().upper())))
    names = [name for name in names if name]
    if len(names) > 100 or any(not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,7}", name) for name in names):
        raise ValueError("Use library names of up to 8 letters, digits or underscores, separated by commas.")
    if any(name in {"WORK", "SASHELP", "SASUSER"} for name in names):
        raise ValueError("WORK, SASHELP and SASUSER are excluded from server snapshots.")
    return names


def catalog_code(token, libraries, libraries_only=False):
    if not re.fullmatch(r"[a-f0-9]{12}", token):
        raise ValueError("Invalid snapshot token.")
    libraries = library_filter(",".join(libraries))
    prefix = "PSC" + token
    where = "libname in (" + ",".join("'" + name + "'" for name in libraries) + ")" if libraries else "libname not in ('WORK','SASHELP','SASUSER')"

    def records(dataset, kind, fields):
        parts = [f"data _null_;\n  set work.{dataset};", "  length _psc_value $4096 _psc_utf8 $16384 _psc_chunk $40 _psc_hex $80;", f"  put '{prefix}|R|{kind}';"]
        for field, expression in fields:
            parts += [f"  _psc_value = {expression};", "  _psc_utf8 = kcvt(trim(_psc_value), getoption('encoding'), 'utf-8');", "  do _psc_i = 1 to lengthn(_psc_utf8) by 40;", "    _psc_chunk = substr(_psc_utf8, _psc_i, 40);", "    _psc_hex = put(_psc_chunk, $hex80.);", f"    put '{prefix}|V|{field}|' _psc_hex;", "  end;"]
        return "\n".join(parts + [f"  put '{prefix}|E';", "run;"])

    emit_libraries = records("_psc_libraries", "library", [("libname", "libname"), ("engine", "engine"), ("path", "path")])
    if libraries_only:
        return f"""/* Discover assigned libraries without opening table metadata. */
options linesize=256 nosyntaxcheck noerrorabend;
data _null_; put '{prefix}|BEGIN'; run;
proc sql;
  create table work._psc_libraries as
  select libname, engine, path from dictionary.libnames where {where};
quit;
{emit_libraries}
data _null_; put '{prefix}|DONE'; run;
"""
    emit_table = records("_psc_one", "table", [
        ("libname", "libname"), ("name", "memname"), ("kind", "memtype"), ("label", "memlabel"),
        ("rows", "strip(put(nobs,best32.))"), ("columns", "strip(put(nvar,best32.))"),
        ("bytes", "strip(put(filesize,best32.))"),
        ("created", "put(crdate,e8601dt19.)"), ("modified", "put(modate,e8601dt19.)")])
    emit_issue = records("_psc_issue", "issue", [("scope", "scope"), ("libname", "libname"), ("name", "memname"), ("message", "message")])
    emit_unreadable = records("_psc_missing", "table", [("libname", "libname"), ("name", "memname"), ("kind", "memtype"), ("readable", "'0'")])
    requested = " ".join(libraries)
    return f"""/* PySAS Servers: best-effort metadata, one library/member at a time.
   No table contents are selected. Library and member names are hex literals,
   so names containing quotes, ampersands or percent signs are never macro code.
   Ordinary metadata errors remain in the SAS log; readable results are retained. */
options linesize=256 nosyntaxcheck noerrorabend obs=max replace;
data _null_; put '{prefix}|BEGIN'; run;
%macro _psc_issue(scope, message);
  data work._psc_issue;
    length scope $12 libname $8 memname $32 message $512;
    scope="&scope"; libname="&_psc_libhex"x; memname="&_psc_memhex"x;
    message="&message";
    output;
  run;
  {emit_issue}
%mend;
%macro _psc_member;
  /* Start empty, so a failed query can never reuse the previous table. */
  data work._psc_one;
    length libname $8 memname $32 memtype $8 memlabel $256
           nobs nvar filesize crdate modate 8;
    stop;
  run;
  proc sql noprint;
    insert into work._psc_one
      select libname, memname, memtype, memlabel, nobs, nvar, filesize,
             crdate, modate from dictionary.tables
      where libname="&_psc_libhex"x and memname="&_psc_memhex"x
        and memtype="&_psc_type";
    %let _psc_rc=&sqlrc;
    %let _psc_rows=&sqlobs;
  quit;
  %if &_psc_rc > 4 or &_psc_rows = 0 %then %do;
    %_psc_issue(table,Metadata could not be read - SQL return code &_psc_rc.. See the refresh log.);
    data work._psc_missing;
      length libname $8 memname $32 memtype $8;
      libname="&_psc_libhex"x; memname="&_psc_memhex"x; memtype="&_psc_type";
    run;
    {emit_unreadable}
  %end;
  %else %do;
    {emit_table}
  %end;
%mend;
%macro _psc_library;
  %local _psc_member_count _psc_j;
  %let _psc_memhex=20;
  /* MEMBERS lists names without requesting each table's detailed metadata. */
  data work._psc_members;
    length libname $8 memname $32 memtype $8;
    stop;
  run;
  proc sql noprint;
    insert into work._psc_members
      select distinct libname, memname, memtype from dictionary.members
      where libname="&_psc_libhex"x and memtype in ('DATA','VIEW');
    %let _psc_rc=&sqlrc;
  quit;
  %if &_psc_rc > 4 %then %do;
    %_psc_issue(library,Library members could not all be listed - SQL return code &_psc_rc.. See the refresh log.);
  %end;
  /* Even if enumeration stopped early, scan any names it did return. */
  proc sql noprint;
    select count(*) into :_psc_member_count trimmed from work._psc_members;
  quit;
  %do _psc_j=1 %to &_psc_member_count;
    data _null_;
      _psc_point=&_psc_j;
      set work._psc_members point=_psc_point;
      call symputx('_psc_memhex',put(memname,$hex64.),'L');
      call symputx('_psc_type',memtype,'L');
      stop;
    run;
    %_psc_member;
  %end;
%mend;
%macro _psc_catalog;
  %local _psc_libhex _psc_memhex _psc_type _psc_rc _psc_rows _psc_count _psc_i _psc_available;
  %let _psc_libhex=20;
  %let _psc_memhex=20;
  data work._psc_libraries;
    length libname $8 engine $8 path $1024;
    stop;
  run;
  proc sql noprint;
    insert into work._psc_libraries
      select libname, engine, path from dictionary.libnames where {where};
    %let _psc_rc=&sqlrc;
  quit;
  %if &_psc_rc > 4 %then %do;
    %_psc_issue(snapshot,Assigned libraries could not all be listed. See the refresh log.);
  %end;
  {emit_libraries}
  proc sql noprint;
    create table work._psc_librefs as select distinct libname from work._psc_libraries;
  quit;
  /* Keep explicitly requested librefs, including unassigned/inaccessible ones. */
  data work._psc_requested;
    length libname $8;
    keep libname;
    do _psc_k=1 to countw('{requested}',' ');
      libname=scan('{requested}',_psc_k,' '); output;
    end;
  run;
  proc append base=work._psc_librefs data=work._psc_requested; run;
  proc sort data=work._psc_librefs nodupkey; by libname; run;
  proc sql noprint;
    select count(*) into :_psc_count trimmed from work._psc_librefs;
  quit;
  %do _psc_i=1 %to &_psc_count;
    data _null_;
      _psc_point=&_psc_i;
      set work._psc_librefs point=_psc_point;
      call symputx('_psc_available',libref(libname)=0,'L');
      call symputx('_psc_libhex',put(libname,$hex16.),'L');
      stop;
    run;
    %let _psc_memhex=20;
    %if &_psc_available = 0 %then %do;
      %_psc_issue(library,Library is unassigned or unavailable in this session.);
    %end;
    %else %do;
      %_psc_library;
    %end;
  %end;
%mend;
%_psc_catalog;
data _null_; put '{prefix}|DONE'; run;
"""


def number(value):
    try:
        value = float(value)
        return int(value) if math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def parse_catalog(text, token, allow_partial=False):
    prefix = "PSC" + token + "|"
    records, current, kind, begun, done = [], None, None, False, False
    issues = []

    def problem(message):
        if not allow_partial:
            raise ValueError(message)
        issues.append({"scope": "snapshot", "libname": "", "name": "", "message": message})

    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(prefix):
            continue
        payload = line[len(prefix):]
        if payload == "BEGIN" and not begun:
            begun = True
        elif payload == "DONE" and begun and not done:
            if current is not None:
                problem("An unfinished metadata record was skipped.")
                current = None
            done = True
        elif payload.startswith("R|") and begun and not done:
            if current is not None:
                problem("An unfinished metadata record was skipped.")
            kind = payload[2:]
            current = {} if kind in {"library", "table", "column", "issue"} else None
            if current is None:
                problem("An unknown metadata record was skipped.")
        elif payload.startswith("V|") and current is not None and not done:
            parts = payload.split("|", 2)
            if len(parts) != 3 or not re.fullmatch(r"[0-9A-Fa-f]{80}", parts[-1].strip()):
                problem("A damaged or truncated metadata record was skipped.")
                current = None
                continue
            _, field, chunk = parts
            current[field] = current.get(field, b"") + bytes.fromhex(chunk.strip())
        elif payload == "E" and current is not None and not done:
            try:
                row = {key: value.rstrip(b" ").decode("utf-8") for key, value in current.items()}
                records.append((kind, row))
            except UnicodeDecodeError:
                problem("An undecodable metadata record was skipped.")
            current = None
        else:
            problem("Incomplete or repeated catalog records in the SAS log.")
    if not begun:
        raise ValueError("No server snapshot was returned. Inspect the refresh log for SAS errors.")
    if not done or current is not None:
        problem("The refresh ended before the catalog was complete. Readable records were retained.")
    libraries, tables, columns = {}, [], []

    def lib(name):
        return libraries.setdefault(name, dict(name=name, engines=[], paths=[], tables=0, views=0,
                                               known_bytes=0, unknown_sizes=0, skipped_members=0, incomplete=False))

    seen = set()
    for kind, row in records:
        if kind == "issue":
            issues.append({key: row.get(key, "") for key in ("scope", "libname", "name", "message")})
            continue
        if not row.get("libname"):
            problem("A metadata record without a library name was skipped.")
            continue
        if kind == "library":
            library = lib(row["libname"])
            for source, target in (("engine", "engines"), ("path", "paths")):
                if row.get(source) and row[source] not in library[target]:
                    library[target].append(row[source])
        elif kind == "column":
            if not row.get("table") or not row.get("name") or row.get("type") not in {"char", "num"}:
                problem("An incomplete column metadata record was skipped."); continue
            for field in ("length", "position"): row[field] = number(row.get(field))
            columns.append(row)
        else:
            row["readable"] = row.get("readable") != "0"
            if not row.get("name") or row.get("kind") not in {"DATA", "VIEW"}:
                problem("An incomplete table metadata record was skipped.")
                continue
            library = lib(row["libname"])
            key = (row["libname"], row["name"], row["kind"])
            if key in seen:
                continue
            seen.add(key)
            for field in ("rows", "columns", "bytes"):
                row[field] = number(row.get(field))
            for field in ("created", "modified"):
                value = row.get(field, "")
                row[field] = value if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", value) else None
            if row["kind"] == "VIEW":
                row["rows"] = row["bytes"] = None
                library["views"] += 1
            else:
                library["tables"] += 1
                if row["bytes"] in (None, 0):
                    row["bytes"] = None
                    library["unknown_sizes"] += 1
                else:
                    library["known_bytes"] += row["bytes"]
            tables.append(row)
    issues = list({tuple(issue.get(k, "") for k in ("scope", "libname", "name", "message")): issue for issue in issues}.values())
    readable_metadata = bool(libraries or tables or columns) or any(i.get("scope") == "columns" and i.get("name") for i in issues)
    for issue in issues:
        if issue.get("libname"):
            library = lib(issue["libname"])
            library["incomplete"] = True
            if issue.get("scope") == "table":
                library["skipped_members"] += 1
                known = next((t for t in tables if t['libname'] == issue['libname'] and t['name'] == issue['name']), None)
                if known:
                    known.update(readable=False, warning=issue['message'])
                elif issue.get('name'):
                    tables.append(dict(libname=issue['libname'], name=issue['name'], kind='UNKNOWN', label='', readable=False, warning=issue['message'], rows=None, columns=None, bytes=None, created=None, modified=None))
                    library['unknown_sizes'] += 1
        else:
            for library in libraries.values():
                library["incomplete"] = True
    if issues and not readable_metadata:
        raise ValueError("No readable library or table metadata was returned. Inspect the refresh log.")
    result = {"libraries": sorted(libraries.values(), key=lambda row: row["name"]),
            "tables": sorted(tables, key=lambda row: (row["libname"], row["name"])),
            "issues": issues, "partial": bool(issues)}
    if columns: result["column_details"] = columns
    return result


def read_catalog(run_dir: Path, token):
    # EG saves the complete log only after Run returns, using the normal runner.
    logs = sorted((run_dir / "logs").glob("*.log"))
    for path in logs:
        text = read_text(path)
        if "PSC" + token + "|BEGIN" in text:
            return parse_catalog(text, token, allow_partial=True)
    raise ValueError("The refresh did not return a catalog log. Inspect its run folder.")


def log_records(token, dataset, kind, fields):
    """ASCII records; UTF-8 bytes survive EG log export and wrapped values."""
    if not re.fullmatch(r"[a-f0-9]{12}", token): raise ValueError("Invalid snapshot token.")
    prefix = 'PSC' + token
    parts = [f"data _null_; set work.{dataset};", "length _psc_value $4096 _psc_utf8 $16384 _psc_chunk $40 _psc_hex $80;", f"put '{prefix}|R|{kind}';"]
    for field, expression in fields:
        parts += [f"_psc_value={expression};", "_psc_utf8=kcvt(trim(_psc_value),getoption('encoding'),'utf-8');", "do _psc_i=1 to lengthn(_psc_utf8) by 40;", "_psc_chunk=substr(_psc_utf8,_psc_i,40); _psc_hex=put(_psc_chunk,$hex80.);", f"put '{prefix}|V|{field}|' _psc_hex; end;"]
    return '\n'.join(parts + [f"put '{prefix}|E'; run;"])


def sas_text(value):
    if not isinstance(value, str) or len(value.encode('utf-8')) > 2048 or any(ord(c)<32 for c in value):
        raise ValueError('Use a single-line text value of up to 2048 UTF-8 bytes.')
    return "'" + value.replace("'", "''") + "'"


def columns_code(token, library, table):
    library = library_filter(library)
    if len(library) != 1: raise ValueError('Choose one library.')
    if not table or len(table.encode('utf-8')) > 128: raise ValueError('Choose a table from the catalog.')
    table_value = "kcvt('"+table.encode('utf-8').hex()+"'x,'utf-8',getoption('encoding'))"
    emit = log_records(token, '_psc_columns', 'column', [(k,v) for k,v in
        [('libname','libname'),('table','memname'),('name','name'),('type','type'),('label','label'),('length','strip(put(length,best32.))'),('position','strip(put(varnum,best32.))'),('format','format'),('informat','informat')]])
    issue = log_records(token, '_psc_issue', 'issue', [('scope',"'columns'"),('libname',sas_text(library[0])),('name',table_value),('message',"'Columns unavailable or collection limit reached; inspect the refresh log.'")])
    return f"""/* One table's column dictionary; no source data is selected. */
options linesize=256 nosyntaxcheck noerrorabend obs=max;
data _null_; put 'PSC{token}|BEGIN'; run;
data work._psc_columns; length libname $8 memname name $32 type $4 label $256 format informat $49 length varnum 8; stop; run;
proc sql noprint outobs=10001;
 insert into work._psc_columns select libname,memname,name,type,label,format,informat,length,varnum from dictionary.columns
 where libname='{library[0]}' and memname={table_value} order by varnum;
 %let _psc_rc=&sqlrc; %let _psc_rows=&sqlobs;
quit;
%macro _psc_column_result;
 %if &_psc_rc > 4 or &_psc_rows = 0 or &_psc_rows > 10000 %then %do;
  data work._psc_issue; x=1; run;
  {issue}
 %end;
%mend;
%_psc_column_result;
data work._psc_columns; set work._psc_columns(obs=10000); run;
{emit}
data _null_; put 'PSC{token}|DONE'; run;
"""


def merge_catalog(previous, patch, level, libraries, table, captured):
    """Refresh only the requested scope. Retain siblings and their timestamps."""
    result = copy.deepcopy(previous or dict(libraries=[], tables=[], issues=[]))
    result.setdefault('column_details', [])
    result.setdefault('refreshes', {})
    refreshed_libs = set(libraries or [l['name'] for l in patch['libraries']])
    libmap = {l['name']:l for l in result['libraries']}
    for library in patch['libraries']:
        old=libmap.get(library['name'], {})
        libmap[library['name']] = {**old, **library, 'assigned': True if library.get('engines') or level=='libraries' else old.get('assigned'), 'discovered': captured if level=='libraries' else old.get('discovered',captured)}
    if level == 'libraries':
        returned = {library['name'] for library in patch['libraries']}
        missing = set(libmap)-returned
        for name in missing:libmap[name]['assigned']=None if patch['partial'] else False
        for row in result['tables']+result['column_details']:
            if row['libname'] in missing:row['stale']=True
    result['libraries'] = list(libmap.values())
    if level in {'tables','full'}:
        incoming = {(t['libname'],t['name']):dict(t, captured=captured) for t in patch['tables']}
        for old in result['tables']:
            key=(old['libname'],old['name'])
            if key not in incoming and (old['libname'] not in refreshed_libs or patch['partial']):
                incoming[key]=dict(old, stale=True) if old['libname'] in refreshed_libs else old
        result['tables']=list(incoming.values())
        for library in refreshed_libs:result['refreshes']['tables:'+library]=dict(captured=captured,partial=patch['partial'])
        for column in result['column_details']:
            if column['libname'] in refreshed_libs:column['stale']=True
    elif level=='columns':
        scope=(libraries[0], table)
        incoming=patch.get('column_details', [])
        old=[c for c in result['column_details'] if (c['libname'],c['table']) != scope]
        if not incoming and patch['partial']:
            old += [dict(c,stale=True) for c in result['column_details'] if (c['libname'],c['table']) == scope]
        room=max(0,100000-len(old))
        if len(incoming)>room:
            incoming=incoming[:room]
            patch=copy.deepcopy(patch);patch['partial']=True
            patch['issues'].append(dict(scope='columns',libname=libraries[0],name=table,message='The connection reached its 100,000-column metadata budget. Choose a narrower connection/library scope.'))
        result['column_details']=old+[dict(c,captured=captured) for c in incoming]
        result['refreshes']['columns:'+libraries[0]+'.'+table]=dict(captured=captured,partial=patch['partial'])
    else:
        result['refreshes']['libraries']=dict(captured=captured,partial=patch['partial'])
    def matches(issue):
        if level=='libraries':return issue.get('scope')=='snapshot'
        if level=='columns':return issue.get('scope')=='columns' and issue.get('libname')==libraries[0] and issue.get('name')==table
        return issue.get('libname') in refreshed_libs and issue.get('scope')!='columns'
    result['issues']=[i for i in result['issues'] if not matches(i)]+patch['issues']
    result['partial']=bool(result['issues'])
    for library in result['libraries']:
        members=[t for t in result['tables'] if t['libname']==library['name']]
        library.update(tables=sum(t['kind']=='DATA' for t in members),views=sum(t['kind']=='VIEW' for t in members),
            known_bytes=sum(t.get('bytes') or 0 for t in members if t['kind']!='VIEW'),
            unknown_sizes=sum(t['kind']!='VIEW' and t.get('bytes') is None for t in members),
            incomplete=any(i.get('libname') in {'',library['name']} for i in result['issues']),
            skipped_members=sum(t.get('readable') is False for t in members))
        library['tables_refreshed']=result['refreshes'].get('tables:'+library['name'])
    result['libraries'].sort(key=lambda l:l['name']); result['tables'].sort(key=lambda t:(t['libname'],t['name']))
    result['captured']=captured;result['libraries_only']=not bool(result['tables'])
    return result
