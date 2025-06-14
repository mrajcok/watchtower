import asyncio, time
import aiosqlite  # https://aiosqlite.omnilib.dev/en/stable/
from   .exceptions         import format_exc, AppTimeoutError, DatabaseError, WithDetailsError
from   .base_db_connection import BaseDbConnection
from   . import config

class SqliteConnection(BaseDbConnection):
    async def open(self, conn_params: dict, timeout=None):
        timeout = timeout or config.get_int(f'{self.resource_id}__db_conn_timeout')
        try:
            self.conn    = await asyncio.wait_for(aiosqlite.connect(conn_params['database']), timeout)
            self.is_open = True
            await self.set_id()
        except asyncio.TimeoutError as e:
            msg = f'{timeout}-sec timeout waiting for a DB connection'
            raise AppTimeoutError(f'{msg} for resource {self.resource_id}', log_msg=msg,
                log_kv_pairs=f'resource_id={self.resource_id} {format_exc(e)}')
        except aiosqlite.Error as e:
            # the exception may contain sensitive information, so raise a custom
            # exception with a more generic msg and the low-level details so we can
            # log the details without exposing them to the client
            msg = f'could not open a DB connection'
            raise DatabaseError(f'{msg} to resource {self.resource_id}', log_msg=msg,
                log_kv_pairs=f'resource_id={self.resource_id} pyodbc_{format_exc(e)}')
        except Exception as e:
            msg = f'could not open a DB connection'
            raise WithDetailsError(f'{msg} to resource {self.resource_id}', log_msg=msg,
                log_kv_pairs=f'resource_id={self.resource_id} {format_exc(e)}')

    async def close(self):
        await self.conn.close()
        self.is_open = False

    _keep_connection_open_errors = ('syntax error', 'no such column', 'no such table')
    async def execute_query(self, query:str, results_as='psv', header=False, timeout=None):
        ''' results_as  value     return type
                        dataframe pandas dataframe
                        json      list[dict]
                        psv       StringIO buffer '''
        timeout    = timeout or config.get_int(f'{self.resource_id}__db_default_query_timeout')
        cursor     = None
        start_time = time.monotonic()
        try:
            cursor  = await asyncio.wait_for(self.conn.execute(query), timeout)
            rows    = await asyncio.wait_for(cursor.fetchall(),        timeout)
            columns = [column[0] for column in cursor.description]

            ## DEBUG random delay to simulate a slow query
            # import random
            # await asyncio.sleep(random.uniform(0.1, 5))
            # for x in range(100000):
            #     print(x, flush=True)

            match results_as:
                case 'dataframe': return self._results_as_dataframe(   rows, columns)
                case 'json':      return self._results_as_json(        rows, columns)
                case 'psv':       return self._results_as_psv_stringio(rows, columns, header)
                case _:
                    raise ValueError(f'unsupported {results_as=!s}')
        except asyncio.TimeoutError as e:
            if cursor:
                await cursor.cancel()  # attempt to cancel the query
            msg = f'{timeout}-sec timeout waiting for DB query or fetch'
            raise AppTimeoutError(f'{msg} from resource {self.resource_id}', log_msg=msg,
                log_kv_pairs=f'resource_id={self.resource_id} {format_exc(e)}')
        except aiosqlite.Error as e:
            msg = f'DB query error'
            err = str(e)
            if any (e in err for e in self._keep_connection_open_errors):
                conn_details = f', keeping connection {self.conn_id} open'
                ##msg += f': {err}'  # maybe okay to show this DB error to the user?
            else:
                await self.close()
                conn_details = f', connection {self.conn_id} closed'
            raise DatabaseError(f'{msg} for resource {self.resource_id}', log_msg=f'{msg}{conn_details}',
                log_kv_pairs=f'resource_id={self.resource_id} {format_exc(e)}')
        except Exception as e:
            msg = f'DB query error'
            raise WithDetailsError(f'{msg} for resource {self.resource_id}', log_msg=msg,
                log_kv_pairs=f'resource_id={self.resource_id} {format_exc(e)}')
        finally:
            if cursor:
                await cursor.close()
            self.usage_duration += round(time.monotonic() - start_time, 3)
        msg = f'DB query error'
        raise WithDetailsError(f'{msg} for resource {self.resource_id}', log_msg=msg,
            log_kv_pairs=f'resource_id={self.resource_id}')
