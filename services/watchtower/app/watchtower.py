#!/bin/python3
import os
from   fastapi import FastAPI
from   prometheus_client import CollectorRegistry, make_asgi_app, multiprocess
from   lib_python.logging           import configure_logging
from   lib_python.resource_manager  import resource_manager
from   lib_python.lifecycle         import lifespan
from   lib_python.middleware        import app_middleware
from   lib_python.sqlite_routes     import router as sqlite_router
from   lib_python.mysql_routes      import router as mysql_router
from   lib_python.mysql_odbc_routes import router as mysql_odbc_router

configure_logging()
resource_manager.add_resources()

# create the FastAPI app, specify the lifespan function, include the routers
# and specify the middleware function
common_responses = {
    429: {'description': 'Too many requests',
          'content': {'application/json': {'example': {'detail': 'TBD'}}}},
    500: {'description': 'Internal server error',
          'content': {'application/json': {'example': {'detail': 'TBD'}}}},
    503: {'description': 'Service unavailable or database error',
          'content': {'application/json': {'example': {'detail': 'TBD'}}}},
    504: {'description': 'Timeout',
          'content': {'application/json': {'example': {'detail': 'TBD'}}}},
}
if os.environ.get('MODE', 'prod') == 'dev':
    app = FastAPI(lifespan=lifespan, responses=common_responses)
else:
    app = FastAPI(lifespan=lifespan, responses=common_responses, openapi_url=None)  # disable docs in production

# if you need to hook into FastAPI's exception handling mechanism
# https://fastapi.tiangolo.com/tutorial/handling-errors/?h=#reuse-fastapis-exception-handlers
# @app.exception_handler(StarletteHTTPException)
# async def custom_http_exception_handler(request, ex):
#     ...do something here...
#     return await http_exception_handler(request, ex)

app.include_router(sqlite_router)
app.include_router(mysql_router)
app.include_router(mysql_odbc_router)
# https://fastapi.tiangolo.com/tutorial/middleware/
app.middleware('http')(app_middleware)

# https://prometheus.github.io/client_python/exporting/http/fastapi-gunicorn/
# http://prometheus.github.io/client_python/multiprocess/
# use the multiprocess collector for registry
def make_metrics_app():
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    return make_asgi_app(registry=registry)
metrics_app = make_metrics_app()
app.mount('/metrics', metrics_app)
