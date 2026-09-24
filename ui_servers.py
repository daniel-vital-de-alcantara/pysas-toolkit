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


def catalog_code(token, libraries):
    if not re.fullmatch(r"[a-f0-9]{12}", token):
        raise ValueError("Invalid snapshot token.")
    libraries = library_filter(",".join(libraries))
    prefix = "PSC" + token
    where = "libname in (" + ",".join("'" + name + "'" for name in libraries) + ")" if libraries else "libname not in ('WORK','SASHELP','SASUSER')"
    def records(dataset, kind, fields):
        parts = [f"data _null_;\n  set work.{dataset};", "  length _psc_value $4096 _psc_utf8 $16384 _psc_chunk $40 _psc_hex $80;", f"  put '{prefix}|R|{kind}';"]
        for field, expression in fields:
            parts += [f"  _psc_value = {expression};", "  _psc_utf8 = kcvt(trim(_psc_value), getoption('encoding'), 'utf-8');", "  do _psc_i = 1 to lengthn(_psc_utf8) by 40;", "    _psc_chunk = substr(_psc_utf8, _psc_i, 40);", "    _psc_hex = put(_psc_chunk, $hex80.);", f"    put '{prefix}|V|{field}|' _psc_hex;", "  end;"]
        parts += [f"  put '{prefix}|E';", "run;"]
        return "\n".join(parts)
    return f"""/* PySAS Servers: metadata snapshot, not table contents.
   The EGP template chooses the connection; shared initialization assigns libs.
   WORK belongs to this fresh session and is deliberately excluded. */
options linesize=256;
proc sql;
  create table work._psc_libraries as
    select libname, engine, path from dictionary.libnames
    where {where};
  create table work._psc_tables as
    select libname, memname, memtype, memlabel, nobs, nvar, filesize,
           crdate, modate from dictionary.tables
    where {where} and memtype in ('DATA','VIEW');
quit;
data _null_; put '{prefix}|BEGIN'; run;
""" + records("_psc_libraries", "library", [("libname", "libname"), ("engine", "engine"), ("path", "path")]) + "\n" + records("_psc_tables", "table", [
        ("libname", "libname"), ("name", "memname"), ("kind", "memtype"), ("label", "memlabel"),
        ("rows", "strip(put(nobs,best32.))"), ("columns", "strip(put(nvar,best32.))"),
        ("bytes", "strip(put(filesize,best32.))"),
        ("created", "put(crdate,e8601dt19.)"), ("modified", "put(modate,e8601dt19.)")]) + f"\ndata _null_; put '{prefix}|DONE'; run;\n"


def number(value):
    try:
        value = float(value)
        return int(value) if math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def parse_catalog(text, token):
    prefix = "PSC" + token + "|"
    records, current, kind, begun, done = [], None, None, False, False
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(prefix):
            continue
        payload = line[len(prefix):]
        if payload == "BEGIN" and not begun:
            begun = True
        elif payload == "DONE" and begun and current is None and not done:
            done = True
        elif payload.startswith("R|") and begun and not done and current is None:
            kind = payload[2:]
            if kind not in {"library", "table"}:
                raise ValueError("Unknown catalog record.")
            current = {}
        elif payload.startswith("V|") and current is not None:
            _, field, chunk = payload.split("|", 2)
            chunk = chunk.strip()
            if not re.fullmatch(r"[0-9A-Fa-f]{80}", chunk):
                raise ValueError("Catalog text was truncated in the SAS log.")
            current[field] = current.get(field, b"") + bytes.fromhex(chunk)
        elif payload == "E" and current is not None:
            records.append((kind, {key: value.rstrip(b" ").decode("utf-8") for key, value in current.items()}))
            current = None
        else:
            raise ValueError("Incomplete or repeated catalog records in the SAS log.")
    if not begun or not done or current is not None:
        raise ValueError("No complete server snapshot was returned. Inspect the refresh log for SAS errors.")
    libraries, tables = {}, []
    def lib(name):
        if not name:
            raise ValueError("Catalog record is missing its library name.")
        return libraries.setdefault(name, dict(name=name, engines=[], paths=[], tables=0, views=0, known_bytes=0, unknown_sizes=0))
    seen = set()
    for kind, row in records:
        library = lib(row.get("libname", ""))
        if kind == "library":
            for source, target in (("engine", "engines"), ("path", "paths")):
                if row.get(source) and row[source] not in library[target]:
                    library[target].append(row[source])
        else:
            if not row.get("name") or row.get("kind") not in {"DATA", "VIEW"}:
                raise ValueError("Catalog table record is incomplete.")
            key = (row["libname"], row["name"], row["kind"])
            if key in seen:
                continue
            seen.add(key)
            for field in ("rows", "columns", "bytes"):
                row[field] = number(row.get(field))
            for field in ("created", "modified"):
                value = row.get(field, "")
                row[field] = value if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", value) else None
            # Views are definitions, not stored rows. An engine's zero is not
            # evidence that a database table consumes no storage.
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
    return {"libraries": sorted(libraries.values(), key=lambda row: row["name"]),
            "tables": sorted(tables, key=lambda row: (row["libname"], row["name"]))}


def read_catalog(run_dir: Path, token):
    # EG saves the complete log only after Run returns, using the normal runner.
    logs = sorted((run_dir / "logs").glob("*.log"))
    for path in logs:
        text = read_text(path)
        if "PSC" + token + "|BEGIN" in text:
            return parse_catalog(text, token)
    raise ValueError("The refresh did not return a catalog log. Inspect its run folder.")
