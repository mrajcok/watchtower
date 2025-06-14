import asyncio, time
from   abc import ABC, abstractmethod
from   io  import StringIO
import pandas as pd
from   . import config

class BaseDbConnection(ABC):
    _next_id = 1
    _lock    = asyncio.Lock()

    def __init__(self, resource_id: str):
        self.conn_id           = 0
        self.resource_id       = resource_id
        self.uses              = 0
        self.created_time_mono = time.monotonic()
        self.is_open           = False
        self.usage_duration    = 0

    def __str__(self):
        age        = int(time.monotonic() - self.created_time_mono)
        mins, secs = divmod(age, 60)
        return f'conn_id={self.conn_id}, conn_age={mins}:{secs:02d}, conn_uses={self.uses}'

    def as_kv_pairs(self):
        'connection details as key-value pairs suitable for logging'
        age        = int(time.monotonic() - self.created_time_mono)
        mins, secs = divmod(age, 60)
        return {
            'conn_id':   self.conn_id,
            'conn_age':  f'{mins}:{secs:02d}',
            'conn_uses': self.uses
        }

    @abstractmethod
    async def close(self):
        pass
    
    @abstractmethod
    async def open(self, conn_params: dict):
        'opens a new DB connection; raises a DatabaseError or WithDetailsError if unable to open'
        pass

    async def set_id(self):
        'must always be called immediately after a successful open'
        async with self._lock:
            self.conn_id               = BaseDbConnection._next_id
            BaseDbConnection._next_id += 1

    def _results_as_dataframe(self, rows, columns):
        return pd.DataFrame.from_records(rows, columns=columns)

    def _results_as_json(self, rows, columns):
        return [dict(zip(columns, row)) for row in rows]

    def _results_as_psv_stringio(self, rows, columns, header):
        results = StringIO()
        if header:
            results.write('|'.join(columns) + '\n')
        results.write('\n'.join(['|'.join(map(str, row)) for row in rows]))
        results.seek(0)
        return results

    @abstractmethod
    async def execute_query(self, query:str, results_as='psv', header=False, timeout=None):
        # subcclasses must update self.usage_duration
        pass

    def reset_usage_duration(self):
        self.usage_duration = 0

    def is_expired(self):
        age = time.monotonic() - self.created_time_mono
        return (self.uses == config.get_int( f'{self.resource_id}__db_conn_max_uses') or
                age        > config.get_eval(f'{self.resource_id}__db_conn_max_age'))

    def increment_use(self):
        self.uses += 1
