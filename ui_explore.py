"""Bounded, read-only SAS previews and dictionary artifacts.

Queries use only catalog identifiers and typed structured filters. All source
reads run in the existing owned EG worker; results travel through its saved log.
"""
from __future__ import annotations
import csv
from decimal import Decimal, InvalidOperation
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import uuid
from pysas import text_encoding
from ui_servers import library_filter, sas_text

MAX_ROWS = 1000
MAX_COLUMNS = 100
WIRE_LIMIT = 2 * 1024 * 1024
CELL_CHARACTERS = 256
DICTIONARY_LIMIT = 100000


def identifier(value):
    if not isinstance(value, str) or not value or len(value.encode('utf-8')) > 128 or any(ord(c)<32 for c in value):
        raise ValueError('Choose a valid catalog identifier.')
    return sas_text(value) + 'n'


def request(catalog, library, table, limit=100, filters=None, join='AND'):
    libraries=library_filter(library)
    if len(libraries)!=1: raise ValueError('Choose one library.')
    member=next((t for t in catalog['tables'] if t['libname']==libraries[0] and t['name']==table),None)
    if not member or member.get('readable') is False or member.get('stale'):
        raise ValueError('Refresh readable table metadata before previewing this table.')
    columns=sorted((c for c in catalog.get('column_details',[]) if c['libname']==libraries[0] and c['table']==table),key=lambda c:c.get('position') or 0)
    stamp=catalog.get('refreshes',{}).get('columns:'+libraries[0]+'.'+table,{})
    if not columns or stamp.get('partial') or any(c.get('stale') for c in columns):
        raise ValueError('Refresh this table’s complete column metadata before previewing it.')
    if isinstance(limit,bool) or not str(limit).isdigit() or not 1<=int(limit)<=MAX_ROWS:
        raise ValueError('Preview rows must be between 1 and 1,000.')
    if join not in {'AND','OR'}:raise ValueError('Filter combination must be AND or OR.')
    filters=[] if filters is None else filters
    if not isinstance(filters,list) or len(filters)>10:raise ValueError('Use at most ten structured filters.')
    if len({c['name'].casefold() for c in columns}) != len(columns):raise ValueError('The saved schema has duplicate column names; refresh it before previewing.')
    known={c['name']:c for c in columns};clauses=[];clean=[]
    operators={'eq':'=','ne':'ne','lt':'<','le':'<=','gt':'>','ge':'>='}
    for item in filters:
        if not isinstance(item,dict) or item.get('column') not in known:raise ValueError('Choose filter columns from the saved schema.')
        col=known[item['column']];name=identifier(col['name']);op=item.get('operator');value=item.get('value','')
        if op in {'missing','not_missing'}:
            clause=('not ' if op=='not_missing' else '')+'missing('+name+')';value=''
        else:
            if col['type']=='num':
                if isinstance(value,bool) or not isinstance(value,(str,int,float)) or len(str(value))>100:raise ValueError('Enter a finite numeric filter value.')
                try:number=Decimal(str(value))
                except InvalidOperation:raise ValueError('Enter a numeric filter value.') from None
                if not number.is_finite() or abs(number)>Decimal('1e308') or (number != 0 and float(number) == 0):raise ValueError('Enter a finite SAS numeric value.')
                literal=str(number);value=literal
            else:
                if not isinstance(value,str) or len(value.encode('utf-8'))>512:raise ValueError('Text filters must be 512 UTF-8 bytes or smaller.')
                # Hex is data, never macro text or an executable SAS expression.
                literal="kcvt('"+(value.encode('utf-8').hex() or '20')+"'x,'utf-8',getoption('encoding'))"
            if op in operators:clause=f'{name} {operators[op]} {literal}'
            elif op in {'contains','starts'} and col['type']=='char':
                if not value:raise ValueError('Enter nonempty search text, or use a missing-value condition.')
                clause=f'index({name},{literal}) '+('> 0' if op=='contains' else '= 1')
            else:raise ValueError('Unsupported operator for this column type.')
        clauses.append('('+clause+')');clean.append(dict(column=col['name'],operator=op,value=value))
    return dict(library=libraries[0],table=table,limit=int(limit),columns=columns[:MAX_COLUMNS],
                omitted_columns=max(0,len(columns)-MAX_COLUMNS),filters=clean,join=join,where=(' '+join+' ').join(clauses))


def sample_code(token, query):
    if not re.fullmatch(r'[a-f0-9]{12}',token):raise ValueError('Invalid preview token.')
    prefix='PXP'+token
    selections=[];values=[];trunc=[]
    for n,col in enumerate(query['columns']):
        source=identifier(col['name']);alias=f'_px_c{n:03}'
        if col['type']=='char':
            selections += [f'ksubstr({source},1,{CELL_CHARACTERS}) as {alias} length=1024',f'(lengthn({source})>{CELL_CHARACTERS}) as _px_t{n:03}']
            values.append(f'_px_values[{n+1}]=kcvt(trim({alias}),getoption(\'encoding\'),\'utf-8\');')
            trunc.append(f'_px_truncated=max(_px_truncated,_px_t{n:03});')
        else:
            selections.append(f'{source} as {alias}')
            values.append(f'_px_values[{n+1}]=strip(put({alias},best32.));')
    count=len(query['columns']);where=' where '+query['where'] if query['where'] else ''
    return f"""/* PySAS bounded preview: reads a source and creates only a private WORK sample.
 Rows are not randomly sampled or ordered. Filters can still require a server scan. */
options linesize=256 nosyntaxcheck noerrorabend obs=max validvarname=any validmemname=extend;
%let _px_sent=0; %let _px_budget=0; %let _px_truncated=0; %let _px_more=0;
data _null_; put '{prefix}|BEGIN'; run;
proc sql noprint noprompt outobs={query['limit']+1};
 create table work._px_sample as select {', '.join(selections)}
 from {query['library']}.{identifier(query['table'])}{where};
 %let _px_rc=&sqlrc;
 %let _px_seen=&sqlobs;
quit;
%macro _px_emit;
%if &_px_seen > {query['limit']} %then %let _px_more=1;
%if &_px_rc <= 4 %then %do;
 data _null_;
  set work._px_sample(obs={query['limit']});
  array _px_values[{count}] $1024 _temporary_;
  length _px_chunk $40 _px_hex $80;
  retain _px_wire 0 _px_truncated 0;
  {' '.join(values)}
  {' '.join(trunc)}
  _px_cost=64;
  do _px_i=1 to {count}; _px_cost+64+120*ceil(lengthn(_px_values[_px_i])/40); end;
  if _px_wire+_px_cost>{WIRE_LIMIT-512} then do;call symputx('_px_budget',1,'G');stop;end;
  _px_wire+_px_cost;
  put '{prefix}|ROW|' _n_;
  do _px_i=1 to {count};
   put '{prefix}|CELL|' _px_i;
   do _px_j=1 to lengthn(_px_values[_px_i]) by 40;
    _px_chunk=substr(_px_values[_px_i],_px_j,40);_px_hex=put(_px_chunk,$hex80.);
    put '{prefix}|V|' _px_hex;
   end;
   put '{prefix}|ENDCELL';
  end;
  put '{prefix}|ENDROW';
  call symputx('_px_sent',_n_,'G');call symputx('_px_truncated',_px_truncated,'G');
 run;
%end;
%else %do;
 data _null_;put '{prefix}|ERROR|SQL query failed; inspect its SAS log.';run;
%end;
%mend;
%_px_emit;
data _null_;put "{prefix}|META|&_px_sent|&_px_more|&_px_budget|&_px_truncated";put '{prefix}|DONE';run;
"""


def parse_sample(lines, token, query):
    prefix='PXP'+token+'|';begun=done=False;rows=[];row=None;cell=None;values=bytearray();wire=0;meta=None
    for line in lines:
        line=line.strip()
        if not line.startswith(prefix):continue
        wire+=len(line)+1
        if wire>WIRE_LIMIT:raise ValueError('Preview exceeded its transport budget.')
        payload=line[len(prefix):]
        if payload=='BEGIN' and not begun:begun=True;continue
        if not begun or done:raise ValueError('Invalid preview record ordering.')
        if payload.startswith('ERROR|'):raise ValueError(payload[6:])
        if payload.startswith('ROW|') and row is None and len(rows)<query['limit']:
            if int(payload[4:])!=len(rows)+1:raise ValueError('Out-of-order preview row.')
            row=[]
        elif payload.startswith('CELL|') and row is not None and cell is None:
            cell=int(payload[5:]);values=bytearray()
            if cell!=len(row)+1 or cell>len(query['columns']):raise ValueError('Invalid preview column.')
        elif payload.startswith('V|') and cell is not None:
            chunk=payload[2:].strip()  # SAS PUT list output may pad a field after the delimiter.
            if not re.fullmatch(r'[a-fA-F0-9]{80}',chunk):raise ValueError('Damaged preview value.')
            values.extend(bytes.fromhex(chunk))
            if len(values)>2048:raise ValueError('Preview cell exceeded its limit.')
        elif payload=='ENDCELL' and cell is not None:
            value=values.rstrip(b' ').decode('utf-8')
            if query['columns'][cell-1]['type']=='num':
                if re.fullmatch(r'\.[A-Z_]?',value):value=None
                else:
                    value=float(value)
                    if not math.isfinite(value):raise ValueError('Invalid numeric preview value.')
            row.append(value);cell=None
        elif payload=='ENDROW' and row is not None and cell is None and len(row)==len(query['columns']):rows.append(row);row=None
        elif payload.startswith('META|') and row is None:
            parts=payload.split('|')
            if len(parts)!=5 or any(not v.isdigit() for v in parts[1:]):raise ValueError('Invalid preview limits.')
            meta=list(map(int,parts[1:]))
        elif payload=='DONE' and row is None and cell is None:done=True
        else:raise ValueError('Incomplete preview records; inspect the SAS log.')
    if not done or meta is None or meta[0]!=len(rows):raise ValueError('Preview ended before all records were returned.')
    return dict(columns=query['columns'],rows=rows,limit=query['limit'],library=query['library'],table=query['table'],
                filters=query['filters'],join=query['join'],omitted_columns=query['omitted_columns'],
                more_rows=bool(meta[1]),transport_limited=bool(meta[2]),cells_truncated=bool(meta[3]),wire_bytes=wire)


def read_sample(folder, token, query):
    for path in sorted((folder/'logs').glob('*.log')):
        with path.open('rb') as raw:encoding=text_encoding(raw.read(4096))
        with path.open(encoding=encoding,errors='replace') as lines:
            # A missing token is distinguished from malformed/truncated result records.
            selected=(line for line in lines if line.strip().startswith('PXP'+token+'|'))
            try:first=next(selected)
            except StopIteration:continue
            import itertools
            return parse_sample(itertools.chain([first],selected),token,query)
    raise ValueError('No preview result was returned; inspect the SAS log.')


def spreadsheet_text(value):
    return "'"+value if isinstance(value,str) and value.lstrip(' \t\r\n').startswith(('=','+','-','@')) else value


def write_csv(path, headers, rows):
    with path.open('w',encoding='utf-8-sig',newline='') as output:
        writer=csv.writer(output);writer.writerow([spreadsheet_text(h) for h in headers])
        writer.writerows([[spreadsheet_text(v) for v in row] for row in rows])


def dictionary_rows(catalog, libraries, query=''):
    chosen=library_filter(libraries);known={l['name'] for l in catalog['libraries']}
    if any(l not in known for l in chosen):raise ValueError('Choose dictionary libraries from this catalog.')
    chosen=set(chosen or known);query=str(query).casefold()
    if len(query)>200:raise ValueError('Dictionary search must be 200 characters or fewer.')
    columns={}
    for col in catalog.get('column_details',[]):columns.setdefault((col['libname'],col['table']),[]).append(col)
    result=[]
    for table in catalog['tables']:
        if table['libname'] not in chosen:continue
        key=(table['libname'],table['name']);stamp=catalog.get('refreshes',{}).get('columns:'+'.'.join(key),{})
        for col in columns.get(key) or [{}]:
            status='Unavailable' if table.get('readable') is False else 'Not collected' if not col else 'Stale' if col.get('stale') else 'Partial' if stamp.get('partial') else 'Collected'
            row=[*key,col.get('name',''),col.get('label',''),col.get('type',''),col.get('length'),col.get('format',''),col.get('informat',''),status,col.get('captured')]
            if not query or any(query in str(v or '').casefold() for v in row[:8]):result.append(row)
            if len(result)>DICTIONARY_LIMIT:raise ValueError('Dictionary exceeds 100,000 rows. Choose fewer libraries.')
    return result

DICTIONARY_HEADERS=['Library','Table','Column','Label','Type','Length','Format','Informat','Metadata status','Captured UTC epoch']


class Jobs:
    """Bounded dictionary collection and export jobs, independent of status polls."""
    def __init__(self,app):self.app=app;self.jobs={};self.lock=threading.RLock()
    def get(self,key):
        with self.lock:
            if key not in self.jobs:raise ValueError('Metadata job not found in this session.')
            return dict(self.jobs[key])
    def start(self,data):
        app=self.app;catalog=app.server_catalog(data.get('snapshot'))
        libraries=library_filter(data.get('libraries',''));dictionary_rows(catalog,','.join(libraries))
        operation=data.get('operation')
        if operation not in {'collect','csv','xlsx'}:raise ValueError('Choose collection, CSV or Excel export.')
        if operation=='collect' and os.name!='nt':raise ValueError('Metadata collection requires Windows and Enterprise Guide.')
        key=uuid.uuid4().hex;job=dict(id=key,status='WORKING',operation=operation,done=0,total=0,message='Preparing dictionary',stop=False)
        job['connection']=catalog.get('connection',data.get('snapshot'))
        with self.lock:
            if any(j['status']=='WORKING' and j['operation']==operation and j.get('connection')==job['connection'] for j in self.jobs.values()):
                raise ValueError('A dictionary operation for this connection is already running.')
            self.jobs[key]=job
        def work():
            try:
                if operation=='collect':
                    candidates=[t for t in catalog['tables'] if (not libraries or t['libname'] in libraries) and t.get('readable') is not False and not t.get('stale')]
                    def missing(t):
                        scope='columns:'+t['libname']+'.'+t['name'];stamp=catalog.get('refreshes',{}).get(scope)
                        return not stamp or stamp.get('partial') or any(c.get('stale') for c in catalog.get('column_details',[]) if c['libname']==t['libname'] and c['table']==t['name'])
                    candidates=[t for t in candidates if missing(t)]
                    selected=candidates[:200];job['total']=len(selected);job['remaining_batch']=max(0,len(candidates)-200);job['failed']=0
                    parent=data['snapshot']
                    for table in selected:
                        if job['stop'] or getattr(app,'closing',False):
                            job['stop']=True;break
                        job['message']='Collecting '+table['libname']+'.'+table['name']
                        try:
                            identifier=app.launch(dict(action='server-refresh',level='columns',parent_snapshot=parent,libraries=table['libname'],table=table['name']))['id']
                            job['command']=identifier
                            while identifier in app.processes:
                                if getattr(app,'closing',False):job['stop']=True
                                time.sleep(.2)
                            command=app.commands[identifier]
                            if command.get('server',{}).get('snapshot'):parent=identifier
                            if command['status']!='SUCCESS':job['failed']+=1
                        except (ValueError,OSError):job['failed']+=1
                        job['done']+=1
                    job.update(status='STOPPED' if job['stop'] else 'READY',snapshot=parent,message=f"{job['done']} tables checked; {job['failed']} incomplete. {job['remaining_batch']} beyond this batch. Stop lets the current file finish; use Stop file in its console to cancel it immediately.")
                else:
                    rows=dictionary_rows(catalog,','.join(libraries),data.get('query',''))
                    target=app.storage/'exports'/('dictionary-'+key)/('data-dictionary.'+operation);target.parent.mkdir(parents=True,exist_ok=True)
                    job['total']=len(rows);job['message']=f'Writing {len(rows)} dictionary rows'
                    if operation=='csv':write_csv(target,DICTIONARY_HEADERS,rows)
                    else:
                        from openpyxl import Workbook
                        from openpyxl.cell import WriteOnlyCell
                        workbook=Workbook(write_only=True);sheet=workbook.create_sheet('Dictionary')
                        for row in [DICTIONARY_HEADERS,*rows]:
                            cells=[]
                            for value in row:
                                cell=WriteOnlyCell(sheet,value=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '\ufffd', value) if isinstance(value,str) else value)
                                if isinstance(value,str):cell.data_type='s'
                                cells.append(cell)
                            sheet.append(cells)
                        workbook.save(target)
                    job.update(status='READY',done=len(rows),path=app.relative(target),message=f'{len(rows)} dictionary rows exported, including explicit missing/incomplete metadata. CSV escapes formula-like text for spreadsheets.')
            except Exception as exc:job.update(status='FAILED',message=str(exc))
        threading.Thread(target=work,daemon=True).start()
        return dict(job)
    def stop(self,key):
        with self.lock:
            if key not in self.jobs or self.jobs[key]['operation']!='collect':raise ValueError('Choose an active dictionary collection.')
            self.jobs[key]['stop']=True
            return dict(self.jobs[key])
    def working(self):return any(j['status']=='WORKING' for j in self.jobs.values())
