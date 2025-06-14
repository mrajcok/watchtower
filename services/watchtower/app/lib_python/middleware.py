import time
from   uuid        import uuid4
from   fastapi.responses import JSONResponse, StreamingResponse
from   fastapi     import Request, Response
from   .logging    import log
from   .shared     import cid_var, acquire_durations_var
from   .shared     import request_counter, request_duration_hist, request_duration_summary
from   .query      import Query
from   .           import config

def log_acquisition_durations(cid:str):
    log_requests = config.getbool('log_request_slot_durations')
    log_db_conns = config.getbool('log_db_conn_durations')
    if not log_requests and not log_db_conns:  return
    kv_pairs  = {}
    durations = acquire_durations_var.get()
    for resource_id, resource_durations in durations.items():
        for acquisition_type, duration in resource_durations.items():
            match acquisition_type:
                case 'request_slot'  if log_requests:
                    kv_pairs[f'{resource_id}_{acquisition_type}_duration'] = duration
                case 'db_connection' if log_db_conns:
                    kv_pairs[f'{resource_id}_{acquisition_type}_duration'] = duration
    kv_pairs['cid'] = cid_var.get()
    log.info('acquisition-stats', 'acquisition durations', **kv_pairs)

def log_query_info(request: Request, cid:str):
    log_type         = config.get('queries_log_type')
    special_log_type = config.get('special_queries_log_type')
    if special_log_type != 'none':
        special_route_pats = config.get('special_queries_routes_patterns').split()
        route_path         = request.scope.get('route').path
        if special_route_pats and any( pat in route_path for pat in special_route_pats ):
            log_type = special_log_type
    if log_type == 'none':  return
    route = request.scope.get('route')
    if not route: return  # this can happen with, e.g., a 404
    streamed_results = route.response_class == StreamingResponse
    kv_pairs         = {'client': request.client.host}
    for i, query in enumerate(request.state.queries, start=1):
        # basic stats are conn_id, duration, row_count
        query: Query  # type hint
        prefix = f'q{i}'
        if log_type == 'stats_with_query' or log_type == 'all':
            kv_pairs[f'{prefix}_query'] = query.query
        kv_pairs[f'conn_id'] = query.conn_id
        kv_pairs['duration'] = query.duration
        if streamed_results:
            kv_pairs[f'{prefix}_row_count'] = '<streamed>'
        else:
            if query.results is None:  kv_pairs[f'{prefix}_row_count'] = '<no rows>'
            else:                      kv_pairs[f'{prefix}_row_count'] = f'{len(query.results)}'
        if log_type == 'stats_with_results' or log_type == 'all':
            if streamed_results:  kv_pairs[f'{prefix}_results'] = '<streamed>'
            else:                 kv_pairs[f'{prefix}_results'] = query.results
    kv_pairs['cid'] = cid_var.get()
    log.info('query-stats', f'{request.method} {request.url.path} query stats', **kv_pairs)

# -- middleware function for "global" request handling
async def app_middleware(request: Request, call_next):
    ''' Creates a correlation ID for the request for logging and tracking purposes
        and puts that in a context variable.
        For routes that are not metrics or FastAPI docs:
        - logs the intial request and then later a summary of the request results/response
        - adds the correlation ID and request duration to the response headers
    '''
    cid_len = config.get_int('cid_len')
    cid     = str(uuid4())[-cid_len:]  # correlation ID
    cid_var.set(cid)
    path = request.url.path
    if path == '/' or path.startswith( ('/metrics', '/docs', '/redoc', '/openapi.json', '/favicon.ico') ):
        return await call_next(request)
    # https://www.starlette.io/requests/#other-state
    start_time = time.monotonic()
    request_counter.labels(request.url.path).inc()
    log.info('request', f'{request.method} {request.url.path}', client=f'{request.client.host}', cid=f'{cid}')
    request.state.queries = []  # Query objects are appended in Query's constructor
    try:
        response:Response = await call_next(request)
        #raise Exception('test exception')  # DEBUG, uncomment to test error handling and grafana display
                                            #        of tracebacks with newlines
    #except HTTPException as e:
        # a FastAPI exception handler would need to be installed to catch these, if desired
    except Exception as e:
        log.exception('traceback', 'unexpected exception processing request',
                       client=f'{request.client.host}', cid=f'{cid}')
        # determine the expected response type for the current route
        route = request.scope.get('route')
        if route and route.response_class == StreamingResponse:
            error_message = f"Error: unexpected exception occurred. {cid=!s}\n"
            response = StreamingResponse(iter([error_message.encode('utf-8')]), media_type="text/plain")
        else:  # default to JSONResponse for other routes
            response = JSONResponse(content={'detail': 'unexpected exception', 'cid': cid}, status_code=500)
    finally:
        request_duration = time.monotonic() - start_time
        response.headers['X-Process-Time']   = str(round(request_duration, 3))
        response.headers['X-Correlation-ID'] = cid
        log_acquisition_durations(cid)
        query_count = len(request.state.queries)
        if query_count:
            log_query_info(request, cid)
        request_duration_hist   .labels(request.url.path).observe(request_duration)
        request_duration_summary.labels(request.url.path, 
            # convert status code to 2xx, 4xx, 5xx for Prometheus
            str(response.status_code)[0]+'xx').observe(request_duration)
        log.info('request-stats', f'{request.method} {request.url.path} results',
                 client=f'{request.client.host}',
                 queries=f'{query_count}',
                 status_code=f'{response.status_code}',
                 # routes that return a StreamingResponse do not have a content-length
                 # so a '-' is used to indicate that
                 content_length=f'{response.headers.get("content-length", "-")}',
                 duration=f'{response.headers["X-Process-Time"]}',
                 cid=f'{cid}')
    return response
