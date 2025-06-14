import asyncio, pyodbc, time
from   .base_db_connection import BaseDbConnection
from   .exceptions         import format_exc, AppTimeoutError, DatabaseError, WithDetailsError
from   .                   import config

class OdbcConnection(BaseDbConnection):
    async def open(self, conn_params: dict, timeout=None):
        loop    = asyncio.get_running_loop()
        timeout = timeout or config.get_int(f'{self.resource_id}__db_conn_timeout')
        try:
            # since pyodbc is not async, run the connection in a separate thread
            # so it does not block any other asyncio tasks
            self.conn = await loop.run_in_executor(
                None,
                lambda: pyodbc.connect(
                    'DRIVER='   f'{conn_params["driver"]};'
                    'SERVER='   f'{conn_params["server"]};'
                    'PORT='     f'{conn_params["port"]};'
                    'DATABASE=' f'{conn_params["database"]};'
                    'USER='     f'{conn_params["user"]};'
                    'PASSWORD=' f'{conn_params["password"]};'
                    'TIMEOUT='  f'{timeout};')
            )
            self.is_open = True
            await self.set_id()
        except pyodbc.Error as e:
            # https://github.com/mkleehammer/pyodbc/wiki/Exceptions
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
        self.conn.close()
        self.is_open = False

    _keep_connection_open_errors = ('SQL syntax', 'Unknown column', '42S02')
        # 42S02 = table not found
    async def execute_query(self, query:str, results_as='psv', header=False, timeout=None):
        ''' results_as: 
            - dataframe - pandas dataframe
            - json      - list[dict]
            - psv       - StringIO buffer '''
        loop       = asyncio.get_running_loop()
        cursor     = self.conn.cursor()
        timeout    = timeout or config.get_int(f'{self.resource_id}__db_default_query_timeout')
        start_time = time.monotonic()
        try:
            # since pyodbc is not async, run the query and fetch in separate threads
            # so they do not block any other asyncio tasks
            await            asyncio.wait_for(loop.run_in_executor(None, cursor.execute, query), timeout)
            rows     = await asyncio.wait_for(loop.run_in_executor(None, cursor.fetchall),       timeout)
            columns  = [column[0] for column in cursor.description]
            match results_as:
                case 'dataframe': return self._results_as_dataframe(   rows, columns)
                case 'json':      return self._results_as_json(        rows, columns)
                case 'psv':       return self._results_as_psv_stringio(rows, columns, header)
                case _:
                    raise ValueError(f'unsupported {results_as=!s} when querying DB resource {self.resource_id}')
        except asyncio.TimeoutError as e:
            cursor.cancel()  # attempt to cancel the ongoing operation
            msg = f'{timeout}-sec timeout waiting for DB query'
            raise AppTimeoutError(f'{msg} for resource {self.resource_id}', log_msg=msg,
                log_kv_pairs=f'resource_id={self.resource_id} {format_exc(e)}')
        except pyodbc.Error as e:
            msg = f'DB query error'
            err = str(e)
            if any (keep_open_txt in err for keep_open_txt in self._keep_connection_open_errors):
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
            if cursor and self.is_open:
                cursor.close()
            self.usage_duration += round(time.monotonic() - start_time, 3)
        raise WithDetailsError(f'{msg} for resource {self.resource_id}', log_msg=msg,
            log_kv_pairs=f'resource_id={self.resource_id}')
