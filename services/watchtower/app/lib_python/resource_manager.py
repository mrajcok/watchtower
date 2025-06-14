import asyncio, os, time
from   fastapi import HTTPException
from   .logging            import log, parse_kv_pairs
from   .request_limiter    import RequestLimiter
from   .db_connection_pool import DbConnectionPool
from   .base_db_connection import BaseDbConnection
from   .mysql_connection   import MysqlConnection
from   .sqlite_connection  import SqliteConnection
from   .odbc_connection    import OdbcConnection
from   .shared             import get_cid, set_duration
from   .exceptions         import AppTimeoutError, ResourceError, format_exc
from   .                   import config

class AcquiredResources:
    ''' Acquired resources and some associated metric durations for the resource_id.
        ResourceManager can modify the fields of this class, since it is tighly coupled. '''
    def __init__(self, resource_id: str):
        self.resource_id               = resource_id
        self.request_slot_acquired     = False
        self.db_conn: BaseDbConnection = None

    async def release(self):
        await resource_manager.release_resources(self)
        self.db_conn               = None
        self.request_slot_acquired = False

    def __del__(self):
        if self.db_conn or self.request_slot_acquired:
            raise RuntimeError(f'resources were not released for {self.resource_id}')
            
class ResourceManager:
    def __init__(self):
        self.request_limiters:    dict[str, RequestLimiter]   = {}
        self.db_connection_pools: dict[str, DbConnectionPool] = {}

    def add_resources(self):
        'creates a DbConnectionPool and a RequestLimiter for each configured resource_id'
        for resource_id in config.get('resource_ids').split():
            db_type = config.get(f'{resource_id}__db_type')
            match db_type:
                case 'mysql':
                    self.db_connection_pools[resource_id] = \
                        DbConnectionPool(resource_id, MysqlConnection, {
                            'host':     config.get(    f'{resource_id}__db_host'),
                            'port':     config.get_int(f'{resource_id}__db_port'),
                            'database': config.get(    f'{resource_id}__db_name'),
                            'user':     config.get(    f'{resource_id}__db_user'),
                            'password': os.environ.get(f'{resource_id}__db_password') or 'root'
                        })
                case 'sqlite':
                    self.db_connection_pools[resource_id] = \
                        DbConnectionPool(resource_id, SqliteConnection, {
                            'database': config.secure_get(f'{resource_id}__db_path')
                        })
                case 'odbc':
                    self.db_connection_pools[resource_id] = \
                        DbConnectionPool(resource_id, OdbcConnection, {
                            'server':   config.get(f'{resource_id}__db_server'),
                            'port':     config.get(f'{resource_id}__db_port'),
                            'driver':   config.secure_get('odbc_driver_path'),
                            'database': config.get(f'{resource_id}__db_name'),
                            # root/root must only be used for dev
                            'user':     config.get(f'{resource_id}__db_user'),
                            'password': os.environ.get(f'{resource_id}__db_password') or 'root'
                        })
                case _:
                    raise ValueError('unsupported db_type')
            self.request_limiters[resource_id] = RequestLimiter(resource_id)

    async def check_db_connections(self):
        for pool in self.db_connection_pools.values():
            await pool.check_connections()

    def create_db_connection_pool_background_tasks(self):
        for pool in self.db_connection_pools.values():
            asyncio.create_task(pool.create_connections())
    
    async def close_db_connections(self):
        for pool in self.db_connection_pools.values():
            await pool.close_connections()

    def acquire_resources(self, resource_ids: list[str]):
        ''' This is a FastAPI dependency injection function.
            https://fastapi.tiangolo.com/tutorial/dependencies/
            A dict of AcquiredResources is returned or a FastAPI HTTPException is raised.
            After the yield statement, the resources are released. '''

        async def dependency_coroutine():
            acquired_resources_dict: dict[str, AcquiredResources] = {}

            async def release_any_resources():
                for resources in acquired_resources_dict.values():
                    await resources.release()

            for resource_id in resource_ids:
                start_time      = time.monotonic()
                request_limiter = self.request_limiters.   get(resource_id)
                pool            = self.db_connection_pools.get(resource_id)
                if not request_limiter or not pool:
                    raise HTTPException(404, get_cid(f'resource {resource_id} not found'))
                # acquire a request slot
                acquired_resources = AcquiredResources(resource_id)
                acquired_resources_dict[resource_id] = acquired_resources
                try:
                    await request_limiter.acquire_slot()
                    acquired_resources.request_slot_acquired = True
                    set_duration(resource_id, 'request_slot', round(time.monotonic() - start_time, 3))
                except asyncio.CancelledError:
                    await release_any_resources()
                    msg = 'request was cancelled due to shutdown of service'
                    log.error('shutdown-cancel', msg, resource_id=f'{resource_id}', cid=get_cid())
                    raise HTTPException(503, get_cid(msg))  # 503 = service unavailable
                except AppTimeoutError as e:
                    await release_any_resources()
                    log.error('slot-timeout', e.log_msg, **parse_kv_pairs(e.log_kv_pairs), cid=get_cid())
                    raise HTTPException(504, get_cid(f'{e}'))  # 504 = gateway timeout
                except ResourceError as e:
                    await release_any_resources()
                    log.error('slot-err', e.log_msg, **parse_kv_pairs(e.log_kv_pairs), cid=get_cid())
                    raise HTTPException(429, get_cid(f'{e}'))  # 429 = too many requests
                except Exception as e:
                    await release_any_resources()
                    msg = f'unable to obtain a request slot for resource {resource_id}'
                    log.error('slot-err', msg, cid=get_cid(), exception=f'{format_exc(e)}')
                    raise HTTPException(500, get_cid(msg))  # 500 = internal server error
                # acquire a DB connection
                start_time = time.monotonic()
                try:
                    conn = await pool.acquire_connection()
                    acquired_resources.db_conn = conn
                    set_duration(resource_id, 'db_connection', round(time.monotonic() - start_time, 3))
                except AppTimeoutError as e:
                    await release_any_resources()
                    log.error('dbconn-timeout', e.log_msg, **parse_kv_pairs(e.log_kv_pairs), cid=get_cid())
                    raise HTTPException(504, get_cid(f'{e}'))
                except Exception as e:
                    await release_any_resources()
                    msg = f'unable to obtain a database connection for resource {resource_id}'
                    log.error('slot-err', msg, cid=get_cid(), exception=f'{format_exc(e)}')
                    raise HTTPException(500, get_cid(msg))
            try:  # this is needed in case the route handler raises an exception
                yield acquired_resources_dict  # code after this will run after the route handler finishes
            # let any exceptions raised by the route handler propagate up and be handled in
            # middleware function app_middleware()
            finally:
                await release_any_resources()
        return dependency_coroutine

    async def release_resources(self, resources: AcquiredResources):
        # release the DB connection, if any, first
        if resources.db_conn:
            await self.db_connection_pools[resources.resource_id].release_connection(resources.db_conn)
        if resources.request_slot_acquired:
            await self.request_limiters[resources.resource_id].release_slot()

resource_manager = ResourceManager()
