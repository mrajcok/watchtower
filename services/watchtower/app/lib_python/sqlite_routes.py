from .logging import log
from   fastapi import APIRouter, Depends, Request
from   fastapi.responses import JSONResponse, StreamingResponse
from   .resource_manager import AcquiredResources, resource_manager
from   .query            import Query
from   .shared           import init_endpoint_metric_children

router      = APIRouter()
resource_id = 'sqlite_traffic'
routes      = '/sqlite-psv /sqlite-json /sqlite-dataframe'.split()
init_endpoint_metric_children(routes)

@router.get('/sqlite-psv', response_class=StreamingResponse,
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

@router.get('/sqlite-json', response_class=JSONResponse,
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
    await query.run(resources[resource_id].db_conn, results_as='json')
    # query.results is a list of dictionaries
    return JSONResponse(content=query.results)

@router.get('/sqlite-dataframe', response_class=JSONResponse,
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
        'SELECT date_hourtt, port, flows, pkts, bytes FROM tcp_hourly LIMIT 10')
    await query.run(resources[resource_id].db_conn, results_as='dataframe')
    # query.results is a pandas DataFrame
    return JSONResponse(content=query.results.to_dict(orient='records'))
