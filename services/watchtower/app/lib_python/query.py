import time
from   fastapi             import HTTPException, Request
from   prometheus_client   import Counter, Histogram
from   .logging            import log, parse_kv_pairs
from   .exceptions         import AppTimeoutError, DatabaseError, WithDetailsError
from   .base_db_connection import BaseDbConnection
from   .shared             import get_cid

_queries_counter      = Counter(  'wt_queries_total',      'total number of queries',      ['resource_id'])
_query_errors_counter = Counter(  'wt_query_errors_total', 'total number of query errors', ['resource_id', 'error_type'])
_query_duration_hist  = Histogram('wt_query_duration_seconds', 'duration to run a query',  ['resource_id'],
                                  # you may want to adjust the buckets
                                  buckets=[0.001, 0.05, 0.1, 0.5, 1, 5, 10, 20])
_query_rows_hist      = Histogram('wt_query_rows', 'number of rows returned by a query', ['resource_id'],
                                    # you may want to adjust the buckets
                                    buckets=[1, 10, 100, 500, 1000, 5000, 10000, 100000])

class Query:
    def __init__(self, request:Request, resource_id:str, query:str):
        request.state.queries.append(self)
        self.resource_id         = resource_id
        self.query               = query
        self.results             = None
        self.conn_id             = -1
        self.duration            = -1
        self.queries_counter     = _queries_counter    .labels(resource_id)
        self.query_duration_hist = _query_duration_hist.labels(resource_id)
        self.query_rows_hist     = _query_rows_hist    .labels(resource_id)
        # initialize children for metrics that have more than one label
        _query_errors_counter.labels(resource_id, 'timeout')
        _query_errors_counter.labels(resource_id, 'other')

    async def run(self, db_conn:BaseDbConnection, results_as='psv', header=False, timeout=None):
        ''' Runs the query and stores the results in self.results or a FastAPI
            HTTPException is raised. results_as can be one of the following: 
            - dataframe - pandas dataframe
            - json      - list[dict]
            - psv       - StringIO buffer '''
        self.queries_counter.inc()
        start_time   = time.monotonic()
        self.conn_id = db_conn.conn_id
        try:
            self.results = await db_conn.execute_query(
                self.query, results_as=results_as, header=header, timeout=timeout)
        except AppTimeoutError as e:
            log.error('query-timeout', e.log_msg, **parse_kv_pairs(e.log_kv_pairs), cid=get_cid())
            _query_errors_counter.labels(self.resource_id, 'timeout')
            raise HTTPException(504, str(e))  # 504 = gateway timeout
        except (DatabaseError, WithDetailsError) as e:
            log.error('query-err', e.log_msg, **parse_kv_pairs(e.log_kv_pairs), cid=get_cid())
            _query_errors_counter.labels(self.resource_id, 'other')
            raise HTTPException(500, str(e))  # 500 = internal server error
        finally:
            self.duration = round(time.monotonic() - start_time, 3)
            self.query_duration_hist.observe(self.duration)
            if hasattr(self.results, '__len__'):
                self.query_rows_hist.observe(len(self.results))
