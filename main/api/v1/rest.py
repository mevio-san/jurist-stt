from fastapi import APIRouter
from api.v1.listener import listener_router
#from core.logger import LoggingRoute

# API Router
v1_router = APIRouter(
    prefix='/v1',
    responses={404: {"description": "Not found"}},
    #route_class=LoggingRoute,
)

for router in [listener_router]:
    v1_router.include_router(router)
