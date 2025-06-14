from   fastapi import APIRouter, Depends, Request
from   fastapi.responses import JSONResponse, StreamingResponse
from   .resource_manager import AcquiredResources, resource_manager
from   .query  import Query
from   .shared import init_endpoint_metric_children, convert_datetime_to_str, convert_timestamp_to_str

router      = APIRouter()
resource_id = 'mysql_traffic'
routes      = '/mysql-odbc-psv /mysql-odbc-json /mysql-odbc-dataframe'.split()
init_endpoint_metric_children(routes)

@router.get('/mysql-odbc-psv', response_class=StreamingResponse,
    responses={
        200: {
            'content': {'text/csv': {'schema': {'type': 'string'}}},
            'description': 'returns query results as PSV, streamed' }
    })
async def psv_request(request: Request,
    resources: dict[str, AcquiredResources] = \
        Depends(resource_manager.acquire_resources([resource_id]))
):
    query = Query(request, resource_id,
        'SELECT date_hour, port, flows, pkts, bytes FROM tcp_hourly LIMIT 10')
    await query.run(resources[resource_id].db_conn, results_as='psv')
    # query.results is a StringIO buffer
    return StreamingResponse(query.results, media_type='text/csv')

@router.get('/mysql-odbc-json', response_class=JSONResponse,
    responses={
        200: {
            'content': {'application/json': {'schema': {'type': 'array'}}},
            'description': 'returns query results as JSON' }
    })
async def json_request(request: Request,
    resources: dict[str, AcquiredResources] = \
        Depends(resource_manager.acquire_resources([resource_id]))
):
    query = Query(request, resource_id,
        'SELECT date_hour, port, flows, pkts, bytes FROM tcp_hourly LIMIT 10')
    conn = resources[resource_id].db_conn
    await query.run(conn, results_as='json')
    # query.results is a list of dictionaries
    convert_datetime_to_str(query.results, 'date_hour')
    return JSONResponse(content=query.results)

@router.get('/mysql-odbc-dataframe', response_class=JSONResponse,
    responses={
        200: {
            'content': {'application/json': {'schema': {'type': 'array'}}},
            'description': 'returns query results as JSON, but internally a DataFrame is used' }
    })
async def dataframe_request(request: Request,
    resources: dict[str, AcquiredResources] = \
        Depends(resource_manager.acquire_resources([resource_id]))
):
    query = Query(request, resource_id,
        'SELECT date_hour, port, flows, pkts, bytes FROM tcp_hourly LIMIT 10')
    conn = resources[resource_id].db_conn
    await query.run(conn, results_as='dataframe')
    # query.results is a pandas DataFrame
    convert_timestamp_to_str(query.results, 'date_hour')
    return JSONResponse(content=query.results.to_dict(orient='records'))
