"""Bounded artifact reads and exact disk indexes for the streaming verifier."""
from hashlib import file_digest
import gzip,json,sqlite3
from pathlib import Path

from .checker import _hash
from .dag_history import _unique_object


class StreamBudgetExceeded(ValueError):pass


def read_json_bound(path,expected_hash,limit):
    path=Path(path)
    with path.open('rb') as stream:actual=file_digest(stream,'sha256').hexdigest()
    if actual!=expected_hash:raise ValueError('STREAM_INPUT_BYTES: '+str(path))
    opener=gzip.open if path.suffix=='.gz' else open
    with opener(path,'rb') as stream:raw=stream.read(limit+1)
    if len(raw)>limit:raise StreamBudgetExceeded('Expanded JSON exceeds explicit per-file byte budget: '+str(path))
    return json.loads(raw,object_pairs_hook=_unique_object),len(raw)


class CertifiedIndex:
    """No probabilistic membership; bounded SQLite cache, full records on disk."""
    def __init__(self,path,cache_mib=16):
        self.path=Path(path);self.db=sqlite3.connect(self.path)
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL');self.db.execute('PRAGMA temp_store=FILE');self.db.execute(f'PRAGMA cache_size={-int(cache_mib*1024)}')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY, hash TEXT NOT NULL, event_hash TEXT NOT NULL, end REAL NOT NULL, status TEXT NOT NULL, chunk INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS results(id TEXT PRIMARY KEY, hash TEXT NOT NULL, body TEXT NOT NULL, chunk INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, hash TEXT NOT NULL, chunk INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS namespaces(kind TEXT NOT NULL,id TEXT NOT NULL,chunk INTEGER NOT NULL,PRIMARY KEY(kind,id));
        CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS stages(protocol TEXT NOT NULL,stage TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(protocol,stage));
        CREATE TABLE IF NOT EXISTS tokens(id TEXT PRIMARY KEY,body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS leases(epoch INTEGER PRIMARY KEY,body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS segments(sequence INTEGER PRIMARY KEY,body TEXT NOT NULL,hash TEXT NOT NULL);
        ''')
    def get_meta(self,key,default=None):
        row=self.db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone();return default if row is None else json.loads(row[0])
    def put_meta(self,key,value):self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,json.dumps(value,ensure_ascii=False,allow_nan=False)))
    def result(self,identity):
        row=self.db.execute('SELECT body FROM results WHERE id=?',(identity,)).fetchone();return None if row is None else json.loads(row[0])
    def action(self,identity):
        row=self.db.execute('SELECT end,status FROM actions WHERE id=?',(identity,)).fetchone();return None if row is None else {'id':identity,'t_end_us':row[0],'status':row[1]}
    def record_hash(self,table,identity,column='hash'):
        if (table,column) not in {('actions','hash'),('actions','event_hash'),('results','hash'),('sources','hash')}:raise ValueError('Unknown hash index')
        row=self.db.execute(f'SELECT {column} FROM {table} WHERE id=?',(identity,)).fetchone();return None if row is None else row[0]
    def node(self,identity):
        row=self.db.execute('SELECT body FROM nodes WHERE id=?',(identity,)).fetchone();return None if row is None else json.loads(row[0])
    def put_node(self,identity,value):self.db.execute('INSERT OR REPLACE INTO nodes VALUES(?,?)',(identity,json.dumps(value,ensure_ascii=False,allow_nan=False)))
    def count(self,table):
        if table not in ('actions','results','sources','segments','nodes','stages','tokens','namespaces'):raise ValueError('Unknown table')
        return self.db.execute('SELECT count(*) FROM '+table).fetchone()[0]
    def bytes(self):return sum(p.stat().st_size for p in self.path.parent.glob(self.path.name+'*') if p.is_file())
    def close(self):self.db.close()
