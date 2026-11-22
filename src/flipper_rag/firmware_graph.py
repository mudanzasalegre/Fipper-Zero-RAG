"""Versioned, queryable firmware knowledge graph backed by SQLite (v0.7).

Read-only Git operations; every snapshot is pinned to a commit SHA. Heuristic C
call references are NOT a verified compiler call graph. The official FAP API
contract is sourced separately from targets/f7/api_symbols.csv.
"""
from __future__ import annotations

from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import replace
import hashlib
from pathlib import Path, PurePosixPath
import re
import sqlite3
import subprocess
from typing import Iterator
from urllib.parse import quote

from .firmware_parser import ParsedFile, Reference, Symbol, parse_c, parse_exports, parse_fam
from .storage import Document, document_id
from .versioning import channel_for_ref, normalize_version

OFFICIAL_REPO = 'https://github.com/flipperdevices/flipperzero-firmware'
REF_PATTERN = re.compile(r'(?:dev|v?\d{1,3}\.\d{1,3}(?:\.\d{1,3})?(?:-rc(?:\.\d+)?)?|[0-9a-f]{40})\Z')
SOURCE_SUFFIXES = {'.c', '.h', '.cpp', '.hpp', '.cc', '.hh'}
MAX_FILES = 20_000
MAX_FILE_BYTES = 524_288
MAX_TOTAL_BYTES = 350_000_000


def _git(repo: Path, *args: str) -> bytes:
    command = ['git', '-C', str(repo), *args]
    p = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=180, check=False)
    if p.returncode:
        raise ValueError('Git failed (' + ' '.join(args[:2]) + '): ' + p.stderr.decode('utf-8','replace')[:350])
    return p.stdout


def _validate_path(path: str) -> bool:
    p = PurePosixPath(path)
    return path and not path.startswith('/') and '..' not in p.parts and not any('\x00' in part for part in p.parts)


def _is_supported(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if not parts or parts[0] not in {'applications', 'applications_user', 'furi', 'lib', 'targets', 'documentation', 'assets'}:
        return False
    if any(x in {'.git', 'node_modules', '.venv', '__pycache__'} for x in parts): return False
    return PurePosixPath(path).suffix.lower() in SOURCE_SUFFIXES or path.endswith('application.fam') or path.endswith('api_symbols.csv')


def resolve_ref(repo: Path, ref: str) -> str:
    if not REF_PATTERN.fullmatch(ref):
        raise ValueError('Ref must be a firmware version tag, dev, or 40-char SHA')
    if re.fullmatch(r'[0-9a-f]{40}', ref):
        rev = ref + '^{commit}'
    elif ref == 'dev':
        rev = 'refs/heads/dev^{commit}'
    else:
        rev = 'refs/tags/' + ref + '^{commit}'
    sha = _git(repo, 'rev-parse', '--verify', rev).decode().strip()
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('Could not resolve Git commit')
    return sha


def _repo_url(repo: Path) -> str:
    try:
        origin = _git(repo, 'remote', 'get-url', 'origin').decode().strip()
    except ValueError:
        return ''
    aliases = {OFFICIAL_REPO, OFFICIAL_REPO+'.git', 'git@github.com:flipperdevices/flipperzero-firmware.git',
               'ssh://git@github.com/flipperdevices/flipperzero-firmware.git'}
    return OFFICIAL_REPO if origin in aliases else ''


def _url(origin: str, sha: str, path: str, line: int = 0) -> str:
    if not origin or not _validate_path(path): return ''
    quoted = '/'.join(quote(s, safe='-_.') for s in path.split('/'))
    return f'{origin}/blob/{sha}/{quoted}' + (f'#L{line}' if line else '')


class FirmwareGraph:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._schema()

    @contextmanager
    def db(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.path, timeout=60)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA busy_timeout=60000')
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def _schema(self):
        with self.db() as c:
            c.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS fw_snapshots (
                  sha TEXT PRIMARY KEY, ref TEXT NOT NULL, repo_url TEXT NOT NULL,
                  channel TEXT NOT NULL, api_version TEXT NOT NULL DEFAULT '',
                  file_count INTEGER NOT NULL, skipped_count INTEGER NOT NULL,
                  symbol_count INTEGER NOT NULL, reference_count INTEGER NOT NULL,
                  complete INTEGER NOT NULL CHECK(complete IN (0,1)),
                  indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS fw_snapshot_refs (
                  ref TEXT PRIMARY KEY, sha TEXT NOT NULL REFERENCES fw_snapshots(sha) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS fw_files (
                  sha TEXT NOT NULL REFERENCES fw_snapshots(sha) ON DELETE CASCADE,
                  path TEXT NOT NULL, content_sha TEXT NOT NULL, size INTEGER NOT NULL,
                  PRIMARY KEY(sha,path)
                );
                CREATE TABLE IF NOT EXISTS fw_symbols (
                  sha TEXT NOT NULL REFERENCES fw_snapshots(sha) ON DELETE CASCADE,
                  id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
                  path TEXT NOT NULL, signature TEXT NOT NULL, line INTEGER NOT NULL,
                  end_line INTEGER NOT NULL, linkage TEXT NOT NULL, evidence TEXT NOT NULL,
                  PRIMARY KEY(sha,id)
                );
                CREATE INDEX IF NOT EXISTS fw_symbols_name ON fw_symbols(sha,name,kind);
                CREATE INDEX IF NOT EXISTS fw_symbols_path ON fw_symbols(sha,path);
                CREATE TABLE IF NOT EXISTS fw_references (
                  sha TEXT NOT NULL REFERENCES fw_snapshots(sha) ON DELETE CASCADE,
                  source TEXT NOT NULL, target_name TEXT NOT NULL,
                  target TEXT, relation TEXT NOT NULL, path TEXT NOT NULL,
                  line INTEGER NOT NULL, resolution TEXT NOT NULL, evidence TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS fw_refs_target ON fw_references(sha,target_name,relation);
                CREATE INDEX IF NOT EXISTS fw_refs_source ON fw_references(sha,source);
                CREATE TABLE IF NOT EXISTS fw_api_exports (
                  sha TEXT NOT NULL REFERENCES fw_snapshots(sha) ON DELETE CASCADE,
                  name TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
                  type TEXT NOT NULL, params TEXT NOT NULL,
                  PRIMARY KEY(sha,name,kind)
                );
                CREATE INDEX IF NOT EXISTS fw_exports_name ON fw_api_exports(sha,name);
            ''')

    def _snapshot(self, c, sha_or_ref: str) -> sqlite3.Row:
        if not isinstance(sha_or_ref, str) or len(sha_or_ref) > 100:
            raise ValueError('Invalid snapshot identifier')
        row = c.execute('''SELECT s.* FROM fw_snapshots s
          LEFT JOIN fw_snapshot_refs r ON r.sha=s.sha
          WHERE s.sha=? OR r.ref=? ORDER BY s.sha LIMIT 1''', (sha_or_ref, sha_or_ref)).fetchone()
        if row is None: raise ValueError(f'Firmware snapshot not indexed: {sha_or_ref}')
        return row

    def snapshots(self) -> list[dict]:
        with self.db() as c:
            rows = c.execute('SELECT * FROM fw_snapshots ORDER BY indexed_at DESC,sha LIMIT 100').fetchall()
            refs = defaultdict(list)
            for r in c.execute('SELECT sha,ref FROM fw_snapshot_refs ORDER BY ref'):
                refs[r['sha']].append(r['ref'])
            return [dict(r) | {'refs': refs[r['sha']]} for r in rows]

    def _resolve_references(self, parsed: list[ParsedFile]) -> list[Reference]:
        symbols = [s for pf in parsed for s in pf.symbols]
        by_name = defaultdict(list)
        paths = {p.path for p in parsed}
        by_base = defaultdict(list)
        for path in paths:
            by_base[PurePosixPath(path).name].append(path)
        for s in symbols:
            by_name[s.name].append(s)
        result = []
        for pf in parsed:
            for ref in pf.references:
                match = None; state = 'unresolved'
                if ref.relation == 'includes':
                    # Quoted includes may be relative to the current file.
                    candidate = str(PurePosixPath(ref.path).parent / ref.target_name)
                    options = [p for p in (candidate, ref.target_name) if p in paths]
                    options = list(dict.fromkeys(options)) or by_base.get(PurePosixPath(ref.target_name).name, [])
                    if len(options) == 1:
                        match, state = 'file:'+options[0], 'resolved'
                    elif len(options) > 1:
                        state = 'ambiguous'
                elif ref.relation in ('requires_app', 'provides_app', 'conflicts_with'):
                    options = [x for x in by_name[ref.target_name] if x.kind == 'app']
                    if len(options) == 1: match, state = options[0].id, 'resolved'
                    elif len(options) > 1: state = 'ambiguous'
                else:
                    functions = [x for x in by_name[ref.target_name] if x.kind == 'function']
                    local = [x for x in functions if x.path == ref.path]
                    global_defs = [x for x in functions if x.linkage == 'global']
                    if len(local) == 1: match, state = local[0].id, 'resolved'
                    elif len(local) > 1: state = 'ambiguous'
                    elif len(global_defs) == 1: match, state = global_defs[0].id, 'resolved'
                    elif len(global_defs) > 1: state = 'ambiguous'
                    else:
                        prototypes = [x for x in by_name[ref.target_name] if x.kind == 'declaration']
                        if len(prototypes) == 1:
                            match, state = prototypes[0].id, 'declaration_only'
                        elif len(prototypes) > 1: state = 'ambiguous'
                result.append(replace(ref, target=match, resolution=state))
        return result

    def index(self, repo: str | Path, ref: str, *, max_files: int = MAX_FILES,
              max_file_bytes: int = MAX_FILE_BYTES, force: bool = False) -> dict:
        repo = Path(repo).expanduser().resolve()
        if not (repo / '.git').exists() and not (repo / 'HEAD').is_file():
            raise ValueError('Expected an existing local Git firmware clone; clone firmware first')
        if max_files < 1 or max_files > 100_000 or max_file_bytes < 1024 or max_file_bytes > 5_000_000:
            raise ValueError('Invalid file limits')
        sha = resolve_ref(repo, ref)
        with self.db() as c:
            existing = c.execute('SELECT * FROM fw_snapshots WHERE sha=?', (sha,)).fetchone()
            if existing and not force:
                c.execute('INSERT OR REPLACE INTO fw_snapshot_refs(ref,sha) VALUES(?,?)', (ref,sha))
                return dict(existing) | {'state': 'unchanged', 'ref': ref}
        entries = []
        for raw_entry in _git(repo, 'ls-tree', '-r', '-l', '-z', sha).split(b'\0'):
            if not raw_entry: continue
            header, path_raw = raw_entry.split(b'\t', 1)
            fields = header.split()
            if len(fields) != 4 or fields[1] != b'blob':continue
            path = path_raw.decode('utf-8', 'replace')
            if _validate_path(path) and _is_supported(path):
                entries.append((path, fields[2], int(fields[3])))
        supported = entries
        if len(supported) > max_files:
            raise ValueError(f'{len(supported)} files exceed max_files={max_files}; refusing partial snapshot')
        parsed = []; files = []; exports = []
        version = ''; skipped = 0; total_bytes = 0
        # A persistent cat-file process avoids launching thousands of Git
        # subprocesses; source files are read by immutable object ID.
        import subprocess as _subprocess
        proc = _subprocess.Popen(['git','-C',str(repo),'cat-file','--batch'],
                                 stdin=_subprocess.PIPE,stdout=_subprocess.PIPE,stderr=_subprocess.PIPE)
        try:
          for path, oid, declared_size in supported:
            if declared_size > max_file_bytes:
                skipped += 1; continue
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(oid+b'\n'); proc.stdin.flush()
            header = proc.stdout.readline().split()
            if len(header)!=3 or header[1]!=b'blob':
                raise ValueError('Git cat-file failed on immutable object')
            size=int(header[2])
            if size!=declared_size or size>max_file_bytes:
                raise ValueError('Git blob size mismatch')
            raw=proc.stdout.read(size)
            if len(raw)!=size or proc.stdout.read(1)!=b'\n':
                raise ValueError('Malformed Git cat-file batch response')
            total_bytes += len(raw)
            if total_bytes > MAX_TOTAL_BYTES:
                raise ValueError('Snapshot exceeds 350MB parsed budget; no partial data committed')
            # Never treat binary assets as source code.
            if b'\0' in raw:
                skipped += 1; continue
            try:
                text = raw.decode('utf-8')
            except UnicodeDecodeError:
                skipped += 1; continue
            files.append((path, hashlib.sha256(raw).hexdigest(), len(raw)))
            if path.endswith('application.fam'):
                parsed.append(parse_fam(path,text))
            elif path.endswith('api_symbols.csv') and path.startswith('targets/'):
                api_version, rows = parse_exports(text)
                if path == 'targets/f7/api_symbols.csv':
                    version, exports = api_version, rows
                parsed.append(ParsedFile(path))
            else:
                parsed.append(parse_c(path,text))
        finally:
            if proc.stdin and not proc.stdin.closed:proc.stdin.close()
            try:proc.wait(timeout=15)
            except _subprocess.TimeoutExpired:
                proc.kill();proc.wait()
            if proc.stderr:proc.stderr.close()
            if proc.stdout:proc.stdout.close()
        references = self._resolve_references(parsed)
        symbols = [symbol for result in parsed for symbol in result.symbols]
        origin = _repo_url(repo)
        channel = 'snapshot' if re.fullmatch(r'[0-9a-f]{40}', ref) else channel_for_ref(ref)
        with self.db() as c:
            c.execute('DELETE FROM fw_snapshots WHERE sha=?', (sha,))
            c.execute('''INSERT INTO fw_snapshots(sha,ref,repo_url,channel,api_version,file_count,
                       skipped_count,symbol_count,reference_count,complete) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                      (sha,ref,origin,channel,version,len(files),skipped,len(symbols),len(references),int(skipped==0)))
            c.executemany('INSERT INTO fw_files(sha,path,content_sha,size) VALUES(?,?,?,?)',
                          ((sha,*item) for item in files))
            c.executemany('''INSERT INTO fw_symbols(sha,id,name,kind,path,signature,line,end_line,linkage,evidence)
                             VALUES(?,?,?,?,?,?,?,?,?,?)''',
                          ((sha,s.id,s.name,s.kind,s.path,s.signature,s.line,s.end_line,s.linkage,s.evidence) for s in symbols))
            c.executemany('''INSERT INTO fw_references(sha,source,target_name,target,relation,path,line,resolution,evidence)
                             VALUES(?,?,?,?,?,?,?,?,?)''',
                          ((sha,r.source,r.target_name,r.target,r.relation,r.path,r.line,r.resolution,r.evidence) for r in references))
            c.executemany('''INSERT INTO fw_api_exports(sha,name,kind,status,type,params)
                             VALUES(?,?,?,?,?,?)''',
                          ((sha,x['name'],x['kind'],x['status'],x['type'],x['params']) for x in exports))
            c.execute('INSERT OR REPLACE INTO fw_snapshot_refs(ref,sha) VALUES(?,?)', (ref,sha))
        return {'state': 'indexed', 'sha': sha, 'ref': ref, 'channel': channel, 'official': bool(origin),
                'api_version': version, 'files': len(files), 'skipped': skipped,
                'complete': skipped==0, 'symbols': len(symbols), 'references': len(references),
                'api_entries':len(exports), 'note':'Heuristic call edges and declarations are not compiler-verified.'}

    @staticmethod
    def _symbol(row: sqlite3.Row, snap: sqlite3.Row) -> dict:
        v = dict(row)
        v['url'] = _url(snap['repo_url'], snap['sha'], v['path'], v['line'])
        v['snapshot'] = snap['sha']
        v['firmware_ref'] = snap['ref']
        v['verified_build'] = False
        return v

    def symbols(self, ref: str, *, query: str = '', kind: str = '', path_prefix: str = '',
                exported_only: bool = False, limit: int = 50, offset: int = 0) -> dict:
        if len(query)>160 or len(kind)>32 or len(path_prefix)>230 or limit not in range(1,201) or offset < 0 or offset > 50000:
            raise ValueError('Invalid symbol query')
        with self.db() as c:
            snap = self._snapshot(c,ref)
            where=['s.sha=?']; params=[snap['sha']]
            if query: where.append('(s.name LIKE ? OR s.signature LIKE ?)');params.extend(('%'+query+'%','%'+query+'%'))
            if kind: where.append('s.kind=?'); params.append(kind)
            if path_prefix: where.append('s.path LIKE ?');params.append(path_prefix+'%')
            if exported_only:
                where.append("EXISTS(SELECT 1 FROM fw_api_exports e WHERE e.sha=s.sha AND e.name=s.name AND e.status='+')")
            w=' AND '.join(where)
            count=c.execute('SELECT COUNT(*) FROM fw_symbols s WHERE '+w,params).fetchone()[0]
            rows=c.execute('SELECT s.* FROM fw_symbols s WHERE '+w+' ORDER BY s.name,s.path,s.line LIMIT ? OFFSET ?',(*params,limit,offset)).fetchall()
            return {'snapshot': snap['sha'],'ref':ref, 'total':count,'results':[self._symbol(r,snap) for r in rows]}

    def symbol(self, ref: str, symbol_id: str) -> dict:
        if not re.fullmatch(r'[0-9a-f]{24}', symbol_id): raise ValueError('Invalid symbol ID')
        with self.db() as c:
            snap=self._snapshot(c,ref)
            row=c.execute('SELECT * FROM fw_symbols WHERE sha=? AND id=?',(snap['sha'],symbol_id)).fetchone()
            if row is None: raise ValueError('Symbol not found')
            info=self._symbol(row,snap)
            info['references_out']=self._references(c,snap, 'source=?',(symbol_id,),40)
            info['references_in']=self._references(c,snap, 'target=?',(symbol_id,),40)
            info['api_exports']=[dict(x) for x in c.execute('SELECT name,kind,status,type,params FROM fw_api_exports WHERE sha=? AND name=?',(snap['sha'],row['name']))]
            return info

    def _references(self,c,snap,where,args,limit):
        rows=c.execute('SELECT source,target_name,target,relation,path,line,resolution,evidence FROM fw_references WHERE sha=? AND '+where+' ORDER BY path,line LIMIT ?', (snap['sha'],*args,limit)).fetchall()
        return [dict(r)|{'url':_url(snap['repo_url'],snap['sha'],r['path'],r['line'])} for r in rows]

    def references(self, ref: str, name: str, *, direction: str = 'both', limit: int = 80) -> dict:
        if not name or len(name)>180 or direction not in {'in','out','both'} or limit not in range(1,201):
            raise ValueError('Invalid reference query')
        with self.db() as c:
            snap=self._snapshot(c,ref)
            candidates=[dict(r) for r in c.execute('SELECT * FROM fw_symbols WHERE sha=? AND name=? ORDER BY path,line LIMIT 30',(snap['sha'],name))]
            ids=[x['id'] for x in candidates]
            result=[]
            if direction in ('in','both'):
                # Incoming candidates that could be unresolved are INCLUDED but clearly labelled.
                result+=self._references(c,snap,'target_name=?',(name,),limit)
            if direction in ('out','both'):
                for sid in ids[:15]:
                    result+=self._references(c,snap,'source=?',(sid,),limit)
            return {'snapshot':snap['sha'],'symbol':name,'definitions':[self._symbol_row(x,snap) for x in candidates],
                    'references':result[:limit],'truncated':len(result)>limit,
                    'note':'Unresolved and ambiguous call-site candidates are not confirmed call edges.'}

    @staticmethod
    def _symbol_row(row,snap):
        return dict(row)|{'url':_url(snap['repo_url'],snap['sha'],row['path'],row['line'])}

    def neighbors(self, ref: str, name: str, *, depth: int = 2, limit: int = 100) -> dict:
        if not 1<=depth<=3 or not 1<=limit<=250 or not name or len(name)>160: raise ValueError('Invalid graph traversal')
        with self.db() as c:
            snap=self._snapshot(c,ref)
            symbols=c.execute('SELECT id FROM fw_symbols WHERE sha=? AND name=? LIMIT 15',(snap['sha'],name)).fetchall()
            frontier=[x[0] for x in symbols];seen=set(frontier); edges=[]
            for _ in range(depth):
                fresh=[]
                for sid in frontier:
                    refs=c.execute("SELECT source,target_name,target,relation,path,line,resolution,evidence FROM fw_references WHERE sha=? AND source=? AND target IS NOT NULL LIMIT 120",(snap['sha'],sid)).fetchall()
                    for r in refs:
                        if len(edges)>=limit:break
                        edges.append(dict(r)|{'url':_url(snap['repo_url'],snap['sha'],r['path'],r['line'])})
                        if r['target'] not in seen:
                            seen.add(r['target']);fresh.append(r['target'])
                    if len(edges)>=limit:break
                frontier=fresh
                if not frontier or len(edges)>=limit:break
            nodes=[]
            if seen:
                for ids in (list(seen)[i:i+300] for i in range(0,len(seen),300)):
                    q=','.join('?'*len(ids))
                    nodes += [self._symbol(r,snap) for r in c.execute('SELECT * FROM fw_symbols WHERE sha=? AND id IN ('+q+')',(snap['sha'],*ids))]
            return {'snapshot':snap['sha'],'query':name,'nodes':nodes,'edges':edges,
                    'truncated':len(edges)>=limit,'note':'Only resolved graph links traversed. Not a compiler call graph.'}

    def exports(self,ref: str,*, query: str='', status: str='', limit: int=100) -> dict:
        if len(query)>160 or status not in ('','+','-','?') or limit not in range(1,501): raise ValueError('Invalid API export query')
        with self.db() as c:
            snap=self._snapshot(c,ref)
            where='sha=?';args=[snap['sha']]
            if query:where+=' AND name LIKE ?';args.append('%'+query+'%')
            if status:where+=' AND status=?';args.append(status)
            rows=c.execute('SELECT name,kind,status,type,params FROM fw_api_exports WHERE '+where+' ORDER BY name LIMIT ?',(*args,limit)).fetchall()
            return {'snapshot':snap['sha'],'api_version':snap['api_version'],
                    'results':[dict(x) for x in rows], 'note':"Only '+' denotes an exported FAP symbol; release compatibility depends on actual API version."}

    def compare(self, before: str, after: str, *, limit: int=150, allow_partial:bool=False) -> dict:
        if before==after:raise ValueError('Compare two different refs or snapshots')
        if not 1<=limit<=1000:raise ValueError('Invalid comparison limit')
        with self.db() as c:
            a,b=self._snapshot(c,before),self._snapshot(c,after)
            if a['sha']==b['sha']:
                return {'before':a['sha'],'after':b['sha'],'same_commit':True,'changes':[], 'api_changes':[], 'counts':{}}
            if (not a['complete'] or not b['complete']) and not allow_partial:
                raise ValueError('Incomplete snapshots cannot be compared without allow_partial')
            def load_symbols(s):
                rows=c.execute('SELECT kind,path,name,signature,line,linkage FROM fw_symbols WHERE sha=?',(s['sha'],)).fetchall()
                return {(r['kind'],r['path'],r['name'],r['linkage']):dict(r) for r in rows}
            old,new=load_symbols(a),load_symbols(b)
            old_keys=set(old);new_keys=set(new)
            changes=[]
            for key in sorted(old_keys & new_keys):
                x,y=old[key],new[key]
                if re.sub(r'\s+',' ',x['signature']).strip() != re.sub(r'\s+',' ',y['signature']).strip():
                    changes.append({'change':'signature_changed','kind':key[0],'name':key[2],
                                    'path_before':key[1],'path_after':key[1],
                                    'before_signature':x['signature'],'after_signature':y['signature'],
                                    'url_before':_url(a['repo_url'],a['sha'],key[1],x['line']),
                                    'url_after':_url(b['repo_url'],b['sha'],key[1],y['line'])})
            removed=set(old_keys-new_keys);added=set(new_keys-old_keys)
            # A unique globally visible symbol can move file without being mislabeled
            # as an add + removal. Internal/static symbols must retain file identity.
            for k in sorted(list(removed)):
                if k[3]!='global': continue
                candidates=[n for n in added if n[0]==k[0] and n[2]==k[2] and n[3]=='global']
                prior=[o for o in removed if o[0]==k[0] and o[2]==k[2] and o[3]=='global']
                if len(candidates)!=1 or len(prior)!=1:continue
                n=candidates[0];removed.remove(k);added.remove(n)
                changes.append({'change':'moved','kind':k[0],'name':k[2],
                                'path_before':k[1],'path_after':n[1],
                                'signature_changed':old[k]['signature']!=new[n]['signature'],
                                'url_before':_url(a['repo_url'],a['sha'],k[1],old[k]['line']),
                                'url_after':_url(b['repo_url'],b['sha'],n[1],new[n]['line'])})
            for k in sorted(removed):
                changes.append({'change':'removed','kind':k[0],'name':k[2],'path_before':k[1],
                                'url_before':_url(a['repo_url'],a['sha'],k[1],old[k]['line'])})
            for k in sorted(added):
                changes.append({'change':'added','kind':k[0],'name':k[2],'path_after':k[1],
                                'url_after':_url(b['repo_url'],b['sha'],k[1],new[k]['line'])})
            def api_map(s):
                return {(r['kind'],r['name']):dict(r) for r in c.execute('SELECT kind,name,status,type,params FROM fw_api_exports WHERE sha=?',(s['sha'],)) if r['status']=='+'}
            old_api,new_api=api_map(a),api_map(b)
            has_api_a = bool(c.execute("SELECT 1 FROM fw_files WHERE sha=? AND path='targets/f7/api_symbols.csv'",(a['sha'],)).fetchone())
            has_api_b = bool(c.execute("SELECT 1 FROM fw_files WHERE sha=? AND path='targets/f7/api_symbols.csv'",(b['sha'],)).fetchone())
            api_changes=[]
            for k in sorted(old_api.keys() | new_api.keys()) if (has_api_a and has_api_b) else []:
                if k not in old_api: api_changes.append({'change':'api_export_added','kind':k[0],'name':k[1],'after':new_api[k]})
                elif k not in new_api: api_changes.append({'change':'api_export_removed','kind':k[0],'name':k[1],'before':old_api[k]})
                elif (old_api[k]['type'],old_api[k]['params'])!=(new_api[k]['type'],new_api[k]['params']):
                    api_changes.append({'change':'api_signature_changed','kind':k[0],'name':k[1],
                                        'before':old_api[k],'after':new_api[k]})
            old_files={r['path']:r['content_sha'] for r in c.execute('SELECT path,content_sha FROM fw_files WHERE sha=?',(a['sha'],))}
            new_files={r['path']:r['content_sha'] for r in c.execute('SELECT path,content_sha FROM fw_files WHERE sha=?',(b['sha'],))}
            file_changes={'added':sum(x not in old_files for x in new_files),
                          'removed':sum(x not in new_files for x in old_files),
                          'modified':sum(old_files.get(x)!=new_files[x] for x in old_files.keys() & new_files.keys())}
            changes.sort(key=lambda x:(x['change'],x['kind'],x['name'],x.get('path_before','')))
            stats={key:sum(x['change']==key for x in changes) for key in ('added','removed','moved','signature_changed')}
            stats.update({key:sum(x['change']==key for x in api_changes) for key in ('api_export_added','api_export_removed','api_signature_changed')})
            return {'before':a['sha'],'after':b['sha'],'refs':[before,after],'api_versions':[a['api_version'],b['api_version']],
                    'complete':bool(a['complete'] and b['complete']),'same_commit':False,
                    'counts':stats,'file_changes':file_changes,'total_symbol_changes':len(changes),
                    'changes':changes[:limit], 'truncated':len(changes)>limit,'api_changes':api_changes[:limit],
                    'api_truncated':len(api_changes)>limit,
                    'api_comparison_status':'compared' if has_api_a and has_api_b else 'unavailable-missing-api-symbols',
                    'note':'A source change does not prove an API break; only api_symbols.csv identifies exported FAP symbols. Snapshot ≠ hardware validation.'}

    def rag_documents(self, ref: str, limit: int = 1000) -> Iterator[Document]:
        if limit not in range(1,5001):raise ValueError('Invalid RAG document limit')
        with self.db() as c:
            snap=self._snapshot(c,ref)
            rows=c.execute('''SELECT * FROM fw_symbols WHERE sha=? AND kind IN ('function','app')
                              ORDER BY path,name LIMIT ?''',(snap['sha'],limit)).fetchall()
            for row in rows:
                calls=[r['target_name'] for r in c.execute('''SELECT DISTINCT target_name FROM fw_references
                      WHERE sha=? AND source=? AND relation='calls' LIMIT 35''',(snap['sha'],row['id']))]
                exported=[r['status'] for r in c.execute('SELECT status FROM fw_api_exports WHERE sha=? AND name=?',(snap['sha'],row['name']))]
                url=_url(snap['repo_url'],snap['sha'],row['path'],row['line'])
                body=(f'# Firmware source: {row["name"]}\n\n'
                      f'Kind: {row["kind"]}\nSignature: {row["signature"]}\n'
                      f'File: {row["path"]} lines {row["line"]}-{row["end_line"]}\n'
                      f'Commit: {snap["sha"]}\n'
                      f'Linkage: {row["linkage"]}\n'
                      f'Exported FAP symbol: {"yes" if "+" in exported else "not established"}\n'
                      f'Call-site candidates: {", ".join(calls) or "none indexed"}\n'
                      f'Source: {url or "local repository; no verified upstream URL"}\n'
                      'C call relations are heuristic; macro expansion, compilation and runtime behavior are not verified.')
                version=''
                if snap['channel'] in ('release','rc'):
                    try:version=normalize_version(snap['ref'])
                    except ValueError:pass
                yield Document(doc_id=document_id(f'firmware-graph-{snap["sha"][:12]}',row['id']),
                               source_id=f'firmware-graph-{snap["sha"][:12]}',
                               title=f'{row["name"]} ({row["path"]})',url=url or f'local://{snap["sha"]}/{row["path"]}',
                               category='firmware-symbol',body=body,revision=snap['sha'],
                               license='Derived index; consult upstream code license',trust='local',
                               firmware_version=version, firmware_channel=snap['channel'])
