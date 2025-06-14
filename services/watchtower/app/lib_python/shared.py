import asyncio
from   collections       import defaultdict
from   contextvars       import ContextVar
from   prometheus_client import Counter, Histogram, Summary

BACKGROUND_TASK_NAME_PREFIX = 'background-task'

cid_var               = ContextVar('correlation-id',    default='')
acquire_durations_var = ContextVar('acquire-durations', default=defaultdict(dict))
shutdown_event        = asyncio.Event()
sigusr1_received      = asyncio.Event()

def get_cid():
    return cid_var.get()

def set_duration(resource_id:str, acquisition_type: str, duration:float):
    durations = acquire_durations_var.get()
    durations[resource_id][acquisition_type] = duration
    acquire_durations_var.set(durations)
    return durations

request_counter       = Counter(  'wt_requests_total', 'total number of requests',  ['endpoint'])
request_duration_hist = Histogram('wt_request_duration_seconds', 'duration to service a request',
    ['endpoint'],
    # you may want to adjust the buckets
    buckets=[0.001, 0.05, 0.1, 0.5, 1, 2.5, 5, 10, 20, 30, 60])
request_duration_summary = Summary('wt_request_duration_summary_seconds', 'duration to service a request',
    ['endpoint', 'status_code'])

def init_endpoint_metric_children(endpoints: list[str]):
     for endpoint in endpoints:
        request_counter      .labels(endpoint)
        request_duration_hist.labels(endpoint)
        for status_code in '2xx 4xx 5xx'.split():
            request_duration_summary.labels(endpoint, status_code)

# some database drivers return datetime objects and likely need to be converted
def convert_datetime_to_str(data, datetime_col, format='%Y-%m-%d %H:%M:%S'):
    "converts datetime objects to strings"
    for row in data:
        row[datetime_col] = row[datetime_col].strftime(format)
    return data

# if a databae driver returned datetime objects and the results were then subsequently
# converted to a pandas DataFrame, the datetime (now pd.Timestamp) objects likely
# need to be converted
def convert_timestamp_to_str(df, timestamp_col, format='%Y-%m-%d %H:%M:%S'):
    "converts panda's Timestamp objects to strings"
    df[timestamp_col] = df[timestamp_col].dt.strftime(format)
    return df
