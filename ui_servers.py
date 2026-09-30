"""Saved SAS library catalogs transported through the existing EG log export.

Only metadata is queried. No shared filesystem, table download or COM polling.
The short ASCII records survive SAS log encodings and line-width limits; text
values are UTF-8 hex chunks, decoded only after the complete record is received.
"""
from __future__ import annotations

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
            current = {} if kind in {"library", "table", "issue"} else None
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
    libraries, tables = {}, []

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
        else:
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
    readable_metadata = bool(libraries or tables)
    for issue in issues:
        if issue.get("libname"):
            library = lib(issue["libname"])
            library["incomplete"] = True
            if issue.get("scope") == "table":
                library["skipped_members"] += 1
        else:
            for library in libraries.values():
                library["incomplete"] = True
    if issues and not readable_metadata:
        raise ValueError("No readable library or table metadata was returned. Inspect the refresh log.")
    return {"libraries": sorted(libraries.values(), key=lambda row: row["name"]),
            "tables": sorted(tables, key=lambda row: (row["libname"], row["name"])),
            "issues": issues, "partial": bool(issues)}


def read_catalog(run_dir: Path, token):
    # EG saves the complete log only after Run returns, using the normal runner.
    logs = sorted((run_dir / "logs").glob("*.log"))
    for path in logs:
        text = read_text(path)
        if "PSC" + token + "|BEGIN" in text:
            return parse_catalog(text, token, allow_partial=True)
    raise ValueError("The refresh did not return a catalog log. Inspect its run folder.")
