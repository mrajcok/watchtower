import asyncio, psutil
import random
from   prometheus_client import Counter, Gauge
from   contextlib import asynccontextmanager
from   datetime   import datetime, timedelta
from   fastapi    import FastAPI
from   .logging   import log
from   .resource_manager import resource_manager
from   .shared import BACKGROUND_TASK_NAME_PREFIX, shutdown_event, sigusr1_received
from   .       import config

async def shutdown():
    #log.info('shutdown', 'shutting down')
    shutdown_event.set()
    await asyncio.sleep(1) # wait briefly for new requests to possibly notice the shutdown flag
    tasks = [t for t in asyncio.all_tasks()
             if t is not asyncio.current_task() and
                (not t.get_name().startswith(BACKGROUND_TASK_NAME_PREFIX)) and
                t.get_coro().__name__ != 'serve' and  # this seems to be the uvicorn server task
                t.get_coro().__name__ != '_serve']    # this seems to be the uvicorn server task under gunicorn
    if tasks:
        log.info('shutdown-wait', f'waiting for {len(tasks)} request tasks to finish')
        for task in tasks:
            log.info('shutdown-wait', f'waiting for {task.get_coro().__name__} {task.get_name()}')
        _, pending = await asyncio.wait(tasks, timeout=2)  ###30)
        if pending:
            log.warning('shutdown-timeout', f'request timeout, {len(pending)} request tasks did not finish')
        else:
            log.info('tasks-done', 'all active request tasks have finished')
    else:
        log.info('shutdown-nowait', 'no active request tasks to wait for')
    await resource_manager.close_db_connections()

_cpu_usage_gauge   = Gauge(f'wt_cpu_usage',       'CPU usage as a percentage',          multiprocess_mode='liveall')
_mem_rss_gauge     = Gauge(f'wt_mem_rss_bytes',   'memory usage (rss) in bytes',        multiprocess_mode='liveall')
_mem_vms_gauge     = Gauge(f'wt_mem_vms_bytes',   'memory usage (rss) in bytes',        multiprocess_mode='liveall')
_mem_shared_gauge  = Gauge(f'wt_mem_shared_bytes','memory usage (rss) in bytes',        multiprocess_mode='liveall')
_mem_percent_gauge = Gauge(f'wt_mem_percent',     'memory usage (rss) as a percentage', multiprocess_mode='liveall')
_open_fds_gauge    = Gauge(f'wt_open_fds',        'number of open file descriptors',    multiprocess_mode='liveall')
_io_read_counter   = Counter(f'wt_io_read_bytes_total',  'bytes passed to read() and pread()',   ['pid'])
_io_write_counter  = Counter(f'wt_io_write_bytes_total', 'bytes passed to write() and pwrite()', ['pid'])
PID                = psutil.Process().pid
io_read_counter    = _io_read_counter .labels(PID)
io_write_counter   = _io_write_counter.labels(PID)

SLEEP_TIME         = 20
async def background_coroutine():
    task_name = f'{BACKGROUND_TASK_NAME_PREFIX}-misc'
    asyncio.current_task().set_name(task_name)
    log.info('task-running', f'task {task_name} is running')
    proc = psutil.Process()
    prev_io_read_chars  = proc.io_counters().read_chars
    prev_io_write_chars = proc.io_counters().write_chars
    try:
        while not shutdown_event.is_set():
            info = proc.as_dict(attrs='cpu_percent memory_info memory_percent num_fds io_counters'.split())
            _cpu_usage_gauge  .set(info['cpu_percent'])
            _mem_rss_gauge    .set(info['memory_info'].rss)
            _mem_vms_gauge    .set(info['memory_info'].vms)
            _mem_shared_gauge .set(info['memory_info'].shared)
            _mem_percent_gauge.set(info['memory_percent'])
            _open_fds_gauge   .set(info['num_fds'])
            io_read_counter   .inc(info['io_counters'].read_chars  - prev_io_read_chars)
            io_write_counter  .inc(info['io_counters'].write_chars - prev_io_write_chars)
            prev_io_read_chars  = info['io_counters'].read_chars
            prev_io_write_chars = info['io_counters'].write_chars
            current_min = datetime.now().minute
            if (current_min % 5) == 0:  # check for expired DB connections every 5 minutes
                await resource_manager.check_db_connections()
            if sigusr1_received.is_set():  # set by handle_sigusr1() in config.py
                log.info('sig-received', f'SIGUSR1 received up to {SLEEP_TIME} secs ago, applying any config overrides now')
                config.apply_overrides()
                sigusr1_received.clear()
                log.setLevel()  # in case the log level changed
            log.info('metrics2', 'metrics test', dtime=f'{(datetime.now() - timedelta(seconds=2)).replace(microsecond=0).isoformat()}', cpu=random.randint(2, 100))
            await asyncio.sleep(SLEEP_TIME)
    except Exception as e:
        log.error('task-exc', f'background task {task_name} exception: {e}', exc_info=True)
    log.info('task-stopping', f'background task {task_name} is exiting')

# https://github.com/fastapi/fastapi/zissues/2713#issuecomment-768949823
# https://fastapi.tiangolo.com/advanced/events/
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(background_coroutine())
    resource_manager.create_db_connection_pool_background_tasks()
    yield
    # the following code will not run until the app starts shutting down
    await shutdown()
