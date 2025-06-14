import asyncio, time
from   prometheus_client import Counter, Gauge, Histogram
from   .           import config
from   .shared     import shutdown_event
from   .exceptions import format_exc, AppTimeoutError, ResourceError

_pending_requests_gauge     = Gauge('wt_pending_requests',           'number of pending requests',
    ['resource_id'], multiprocess_mode='livesum')
_in_progress_requests_gauge = Gauge('wt_in_progress_requests',       'number of in progress requests',
    ['resource_id'], multiprocess_mode='livesum')
_last_request_time_guage    = Gauge('wt_last_request_time_seconds',  'last time a request was received',
    ['resource_id'], multiprocess_mode='mostrecent')
_last_response_time_guage   = Gauge('wt_last_response_time_seconds', 'last time a response was sent',
    ['resource_id'], multiprocess_mode='mostrecent')
_resource_request_counter   = Counter('wt_resource_requests_total',  'total number of requests for a resource ID',
    ['resource_id'])
_request_slot_error_counter = Counter('wt_request_slot_errors_total','total number of request slot errors',
    ['resource_id', 'error_type'])
_request_slot_acquire_durations  = Histogram('wt_request_slot_acquire_duration_seconds',
    'duration to acquire a request slot', ['resource_id'], buckets=[0.001, 0.01, 0.05, 0.1, 0.5, 1, 5, 10, 20])

class RequestLimiter:
    'limits/throttles client requests for a particular database resource'

    def __init__(self, resource_id: str):
        self.resource_id = resource_id
        self.lock        = asyncio.Lock()
        self.pending_requests_count = 0
        self.active_requests_count  = 0
        self.pending_requests_gauge         = _pending_requests_gauge        .labels(resource_id)
        self.in_progress_requests_gauge     = _in_progress_requests_gauge    .labels(resource_id)
        self.last_request_time_gauge        = _last_request_time_guage       .labels(resource_id)
        self.last_response_time_gauge       = _last_response_time_guage      .labels(resource_id)
        self.resource_request_counter       = _resource_request_counter      .labels(resource_id)
        self.request_slot_acquire_durations = _request_slot_acquire_durations.labels(resource_id)
        self.semaphore = asyncio.Semaphore(config.get_int(f'{resource_id}__max_active_requests'))
        # initialize children for metrics that have more than one label
        _request_slot_error_counter.labels(resource_id, 'timeout')
        _request_slot_error_counter.labels(resource_id, 'overload')

    async def acquire_slot(self):
        self.last_request_time_gauge.set_to_current_time()
        self.resource_request_counter.inc()
        if shutdown_event.is_set():
            raise asyncio.CancelledError('server is shutting down')
        max_pending_requests = config.get_int(f'{self.resource_id}__max_pending_requests')
        async with self.lock:
            if self.pending_requests_count == max_pending_requests:
                msg = f'too many pending requests'
                _request_slot_error_counter.labels(self.resource_id, 'overload').inc()
                raise ResourceError(f'{msg} for resource {self.resource_id}', log_msg=msg,
                    log_kv_pairs=f'resource_id={self.resource_id} {max_pending_requests=!s}')
            self.pending_requests_count += 1
            self.pending_requests_gauge.inc()
        acquired   = False
        start_time = time.monotonic()
        timeout    = config.get_int(f'{self.resource_id}__request_slot_timeout')
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout)
            self.request_slot_acquire_durations.observe(time.monotonic() - start_time)
            acquired = True
        except asyncio.TimeoutError as e:
            msg = f'{timeout}-sec timeout waiting for a request slot'
            _request_slot_error_counter.labels(self.resource_id, 'timeout').inc()
            raise AppTimeoutError(f'{msg} for resource {self.resource_id}', log_msg=msg,
                    log_kv_pairs=f'resource_id={self.resource_id} {format_exc(e)}')
        finally:
            async with self.lock:
                self.pending_requests_count -= 1
                self.pending_requests_gauge.dec()
                if acquired:
                    self.active_requests_count += 1
                    self.in_progress_requests_gauge.inc()

    async def release_slot(self):
        async with self.lock:
            self.active_requests_count -= 1
            self.in_progress_requests_gauge.dec()
        self.semaphore.release()
        self.last_response_time_gauge.set_to_current_time()
