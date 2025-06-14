import asyncio, time
import aiomysql  # https://aiomysql.readthedocs.io/
from   .exceptions         import format_exc, AppTimeoutError, DatabaseError, WithDetailsError
from   .base_db_connection import BaseDbConnection
from   . import config

class MysqlConnection(BaseDbConnection):
    async def open(self, conn_params: dict, timeout=None):
        timeout = timeout or config.get_int(f'{self.resource_id}__db_conn_timeout')
        try:
            self.conn = await aiomysql.connect(
                host            = conn_params['host'],
                port            = conn_params['port'],
                user            = conn_params['user'],
                password        = conn_params['password'],
                db              = conn_params['database'],
                autocommit      = True,
                connect_timeout = timeout)
            self.is_open = True
            await self.set_id()
        except aiomysql.Error as e:
            error_code = e.args[0]
            error_msg  = e.args[1]
            if error_code == 2003 and 'time' in error_msg:
                msg = f'{timeout}-sec timeout waiting for a DB connection'
                raise AppTimeoutError(f'{msg} for resource {self.resource_id}', log_msg=msg,
                    log_kv_pairs=f'resource_id={self.resource_id} {format_exc(e)}')
            # the exception may contain sensitive information, so raise a custom
            # exception with a more generic msg and the low-level details so we can
            # log the details without exposing them to the client
            msg = f'could not open a DB connection'
            raise DatabaseError(f'{msg} to resource {self.resource_id}', log_msg=msg,
                log_kv_pairs=f'resource_id={self.resource_id} aiomsql_{format_exc(e)}')
        except Exception as e:
            msg = f'could not open a DB connection'
            raise WithDetailsError(f'{msg} to resource {self.resource_id}', log_msg=msg,
                log_kv_pairs=f'resource_id={self.resource_id} {format_exc(e)}')

    async def close(self):
        self.conn.close()
        self.is_open = False

    _keep_connection_open_errors = ('SQL syntax', 'Unknown column')
    async def execute_query(self, query:str, results_as='psv', header=False, timeout=None):
        ''' results_as  value     return type
                        dataframe pandas dataframe
                        json      list[dict]
                        psv       StringIO buffer '''
        timeout    = timeout or config.get_int(f'{self.resource_id}__db_default_query_timeout')
        cursor     = None
        start_time = time.monotonic()
        try:
            cursor  = await self.conn.cursor()
            await asyncio.wait_for(cursor.execute(query), timeout)
            rows    = await asyncio.wait_for(cursor.fetchall(), timeout)
            columns = [column[0] for column in cursor.description]
            match results_as:
                case 'dataframe': return self._results_as_dataframe(   rows, columns)
                case 'json':      return self._results_as_json(        rows, columns)
                case 'psv':       return self._results_as_psv_stringio(rows, columns, header)
                case _:
                    raise ValueError(f'unsupported {results_as=!s}')

            ## DEBUG random delay to simulate a slow query
            import random
            await asyncio.sleep(random.uniform(0.1, 5))

        except asyncio.TimeoutError as e:
            msg = f'{timeout}-sec timeout waiting for DB query or fetch'
            raise AppTimeoutError(f'{msg} from resource {self.resource_id}', log_msg=msg,
                log_kv_pairs=f'resource_id={self.resource_id} {format_exc(e)}')
        except aiomysql.ProgrammingError as e:
            # programming errors are usually due to bad SQL syntax, not a connection issue
            msg = f'DB query error'
            err = e.args[1]
            conn_details = f', keeping connection {self.conn_id} open'
            raise DatabaseError(f'{msg} for resource {self.resource_id}',
                log_msg=f'{msg}{conn_details}',
                log_kv_pairs=f'resource_id={self.resource_id} {format_exc(e)}')
        except aiomysql.OperationalError as e:
            # some operational errors, like 'Unknown column', are not connection issues, but
            # others, like 'Lost connection to ...', are connection issues
            msg = f'DB query error'
            err = e.args[1]
            if any (e in err for e in self._keep_connection_open_errors):
                conn_details = f', keeping connection {self.conn_id} open'
                ##msg += f': {err}'  # maybe okay to show this DB error to the user?
            else:
                await self.close()
                conn_details = f', connection {self.conn_id} closed'
            raise DatabaseError(f'{msg} for resource {self.resource_id}',
                log_msg=f'{msg}{conn_details}',
                log_kv_pairs=f'resource_id={self.resource_id} {format_exc(e)}')
        except aiomysql.Error as e:
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
