import asyncio, time
from   prometheus_client   import Counter, Gauge, Histogram
from   .logging            import log, parse_kv_pairs
from   .exceptions         import AppTimeoutError, DatabaseError, WithDetailsError
from   .base_db_connection import BaseDbConnection
from   .shared             import BACKGROUND_TASK_NAME_PREFIX, get_cid, shutdown_event
from   .                   import config

_created_conn_counter        = Counter(f'wt_created_connections_total',
    'total number of connections created', ['resource_id'])
_closed_conn_counter         = Counter(f'wt_closed_connections_total',
    'total number of connections closed', ['resource_id'])
_pool_empty_counter          = Counter(f'wt_pool_empty_total',
    'total number of times the pool was empty', ['resource_id'])
_pool_exhausted_counter      = Counter(f'wt_pool_exhausted_total',
    'total number of times the pool was exhausted', ['resource_id'])
_conn_creation_error_counter = Counter(f'wt_conn_creation_errors_total',
    'total number of connection creation errors', ['resource_id', 'error_type'])
_conn_acquire_error_counter  = Counter(f'wt_conn_acquire_errors_total',
    'total number of connection acquire errors', ['resource_id'])
_conn_gauge                  = Gauge(  f'wt_open_connections',
    'number of open connections',           ['resource_id'], multiprocess_mode='livesum')
_pooled_conn_gauge           = Gauge(  f'wt_pooled_connections',
    'number of connections in the pool',    ['resource_id'], multiprocess_mode='livesum')
_last_conn_created_time_gauge = Gauge(f'wt_last_conn_created_time_seconds',
    'time the last connection was created', ['resource_id'], multiprocess_mode='mostrecent')
_last_conn_created_error_time_gauge = Gauge(f'wt_last_conn_created_error_time_seconds',
    'time the last connection creation error occurred', ['resource_id'], multiprocess_mode='mostrecent')
# use histograms so we can aggregate across all resource_ids
_acquire_conn_hist = Histogram(f'wt_acquire_connection_duration_seconds',
    'time to acquire a connection', ['resource_id'],
    buckets=[0.001, 0.01, 0.05, 0.1, 0.5, 1, 5, 10])
_conn_usage_hist   = Histogram(f'wt_connection_usage_duration_seconds',
    'how long a connection was used to service a request', ['resource_id'],
    # you may want to adjust these buckets
    buckets=[0.001, 0.01, 0.05, 0.1, 0.5, 1, 5, 10, 20])

class DbConnectionPool:
    ''' a pool of DB connections for a single resource_id '''
    _pools: dict[str, 'DbConnectionPool'] = {}
  
    def __init__(self, resource_id: str, conn_class:BaseDbConnection, conn_params:dict):
        self.resource_id    = resource_id
        max_connections     = config.get_int(f'{resource_id}__db_max_conn_pool_size')
        self.pool           = asyncio.Queue(max_connections)
        self.add_conn_queue = asyncio.Queue(max_connections)
        self.lock           = asyncio.Lock()
        self.conn_count     = 0  # same count as conn_guage
        self.conn_class     = conn_class
        self.conn_params    = conn_params
        self.consecutive_create_conn_errors = 0
        self.created_conn_counter               = _created_conn_counter              .labels(resource_id)
        self.closed_conn_counter                = _closed_conn_counter               .labels(resource_id)
        self.pool_empty_counter                 = _pool_empty_counter                .labels(resource_id)
        self.pool_exhausted_counter             = _pool_exhausted_counter            .labels(resource_id)
        self.conn_acquire_error_counter         = _conn_acquire_error_counter        .labels(resource_id)
        self.conn_gauge                         = _conn_gauge                        .labels(resource_id)
        self.pooled_conn_gauge                  = _pooled_conn_gauge                 .labels(resource_id)
        self.last_conn_created_time_gauge       = _last_conn_created_time_gauge      .labels(resource_id)
        self.last_conn_created_error_time_gauge = _last_conn_created_error_time_gauge.labels(resource_id)
        self.acquire_conn_hist                  = _acquire_conn_hist                 .labels(resource_id)
        self.conn_usage_hist                    = _conn_usage_hist                   .labels(resource_id)
        # initialize children for metrics that have more than one label
        _conn_creation_error_counter.labels(resource_id, 'timeout')
        _conn_creation_error_counter.labels(resource_id, 'other')
        for _ in range(config.get_int(f'{resource_id}__db_min_conn_pool_size')):
            log.debug('dbconn-req', 'requesting a new conn be put into pool', resource_id=f'{self.resource_id}')
            self.add_conn_queue.put_nowait(1)

    async def close_connections(self):
        log.info('dbconn-close', f'closing {self.conn_count} connections', resource_id=f'{self.resource_id}')
        # the program is shutting down, so don't bother with the lock
        while not self.pool.empty():
            db_conn:BaseDbConnection = self.pool.get_nowait()
            await db_conn.close()
            self.conn_count -= 1
            self.conn_gauge.dec()
            self.pooled_conn_gauge.dec()
            self.closed_conn_counter.inc()

    async def acquire_connection(self, timeout=None):
        ''' Returns a connection from the pool.
            If a connection cannot be obtained, an AppTimeoutError is raised. ''' 
        start_time    = time.monotonic()
        conn_obtained = False
        async with self.lock:
            if self.pool.empty():
                self.pool_empty_counter.inc()
                if self.conn_count < (config.get_int(f'{self.resource_id}__db_max_conn_pool_size')
                                      + self.add_conn_queue.qsize()):
                    log.debug('dbconn-req', 'pool empty, requesting a new connection', 
                              resource_id=f'{self.resource_id}', cid=get_cid())
                    # signal the background task to create a new connection
                    self.add_conn_queue.put_nowait(1)
                else:
                    log.debug('dbpool-exhausted', 'pool exhausted', resource_id=f'{self.resource_id}', cid=get_cid())
                    self.pool_exhausted_counter.inc()
        if not conn_obtained:
            timeout = timeout or config.get_int(f'{self.resource_id}__db_conn_pool_acquire_timeout')
            try:
                # wait for a connection to be put into the pool, which might not happen
                # before the timeout
                db_conn:BaseDbConnection = await asyncio.wait_for(self.pool.get(), timeout)
                self.pooled_conn_gauge.dec()
            except asyncio.TimeoutError as e:
                msg = f'{timeout}-sec timeout waiting for a pooled connection'
                self.conn_acquire_error_counter.inc()
                # str(e) is empty, so don't add log_kv_pairs below
                raise AppTimeoutError(f'{msg} for {self.resource_id}', log_msg=msg,
                                      log_kv_pairs=f'resource_id={self.resource_id}')
        self.acquire_conn_hist.observe(round(time.monotonic() - start_time, 3))
        db_conn.reset_usage_duration()
        return db_conn

    async def release_connection(self, db_conn: BaseDbConnection):
        db_conn.increment_use()
        self.conn_usage_hist.observe(db_conn.usage_duration)
        if db_conn.is_expired():
            log.debug('dbconn-expired', 'connection expired', **db_conn.as_kv_pairs(),
                      resource_id=f'{self.resource_id}')
            await db_conn.close()
            async with self.lock:
                self.conn_count -= 1
                self.closed_conn_counter.inc()
                self.conn_gauge.dec()
                self.add_conn_queue.put_nowait(1)
        else:
            async with self.lock:
                self.pool.put_nowait(db_conn)
                self.pooled_conn_gauge.inc()
                # since f-strings are evaluated even if the log level is not enabled,
                # check the level first, especially since we have the lock
                if config.get('log_level') == 'DEBUG':
                    log.debug('dbconn-released', 'connection put back in pool', **db_conn.as_kv_pairs(),
                              resource_id=f'{self.resource_id}', conn_count=f'{self.conn_count}')

    async def create_connections(self):
        'this background task/coroutine creates new connections and puts them in the pool'
        task_name = f'{BACKGROUND_TASK_NAME_PREFIX}-{self.resource_id}-connections'
        asyncio.current_task().set_name(task_name)
        log.info('task-running', f'task {task_name} is running')
        while not shutdown_event.is_set():
            await self.add_conn_queue.get()
            async with self.lock:
                if self.conn_count == config.get_int(f'{self.resource_id}__db_max_conn_pool_size'):
                    # the max number of connections are open, so don't create any more connections
                    continue
            log.debug('dbconn-req', 'about to create a new DB connection', resource_id=f'{self.resource_id}')
            db_conn:BaseDbConnection = self.conn_class(self.resource_id)
            sleep_time = config.get_int(f'{self.resource_id}__db_conn_retry_wait_period')
            try:
                await db_conn.open(self.conn_params)
            except AppTimeoutError as e:
                _conn_creation_error_counter.labels(self.resource_id, 'timeout').inc()
                log.error('dbconn-timeout', e.log_msg, **parse_kv_pairs(e.log_kv_pairs))
                sleep_time = 0
            except (DatabaseError, WithDetailsError) as e:
                _conn_creation_error_counter.labels(self.resource_id, 'other').inc()
                log.error('dbconn-err', e.log_msg, **parse_kv_pairs(e.log_kv_pairs))
            if db_conn.is_open:
                self.last_conn_created_time_gauge.set_to_current_time()
                self.created_conn_counter.inc()
                self.conn_gauge.inc()
                async with self.lock:
                    self.conn_count += 1
                    await self.pool.put(db_conn)
                    self.pooled_conn_gauge.inc()
                log.debug('dbconn-added', 'new connection put into pool by background task',
                          conn_id=f'{db_conn.conn_id}', resource_id=f'{self.resource_id}')
                self.consecutive_create_conn_errors = 0
            else:
                self.last_conn_created_error_time_gauge.set_to_current_time()
                self.add_conn_queue.put_nowait(1)  # try again
                self.consecutive_create_conn_errors += 1
                if self.consecutive_create_conn_errors and self.consecutive_create_conn_errors % 5 == 0:
                    log.error('dbconn-err', f'background task failed {self.consecutive_create_conn_errors} '
                              f'consecutive times to open a new connection', resource_id=f'{self.resource_id}')
                # sleep to avoid possibly trying to create a connection in a tight loop
                log.debug('task-sleep', f'background task sleeping {sleep_time} secs before open conn retry',
                          resource_id=f'{self.resource_id}')
                await asyncio.sleep(sleep_time)

    async def check_connections(self):
        'removes any expired connections from the pool'
        log.debug('dbconn-check', 'checking connections', resource_id=f'{self.resource_id}')
        not_expired_conns = []
        async with self.lock: 
            while not self.pool.empty():
                db_conn:BaseDbConnection = await self.pool.get()
                if db_conn.is_expired():
                    log.debug('dbconn-expired', 'connection expired', **db_conn.as_kv_pairs(),
                               resource_id=f'{self.resource_id}')
                    await db_conn.close()
                    self.conn_count -= 1
                    self.closed_conn_counter.inc()
                else:
                    not_expired_conns.append(db_conn)
            for conn in not_expired_conns:
                await self.pool.put(conn)
                log.debug('dbconn-keep', f'connection kept in pool', **db_conn.as_kv_pairs(),
                           resource_id=f'{self.resource_id}')
            for _ in range(config.get_int(f'{self.resource_id}__db_min_conn_pool_size') - self.conn_count
                           - self.add_conn_queue.qsize()):
                log.debug('deconn-req', 'requesting a new conn be put into pool', resource_id=f'{self.resource_id}')
                self.add_conn_queue.put_nowait(1)
            self.pooled_conn_gauge.set(self.pool.qsize())
            self.conn_gauge.set(self.conn_count)
