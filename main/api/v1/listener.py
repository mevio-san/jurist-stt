from fastapi import (
    APIRouter,
    Depends,
    Path,
    WebSocket,
    WebSocketDisconnect,
)
from services.stt.audio_adapter import STTAudioAdapter
from services.stt.models_pool import ModelsPool

MAX_CONCURRENT_MODELS = 4

_pool = ModelsPool(MAX_CONCURRENT_MODELS)

#from core.logger import LoggingRoute
from api.security import websocket_api_key_credentials


listener_router = APIRouter(
    prefix="/listen",
    tags=["listener"],
    responses={404: {"description": "Not found"}},
    #route_class=LoggingRoute,
)

@listener_router.websocket("")
@websocket_api_key_credentials
async def listen(
    websocket: WebSocket,
    encoding: str = 'mulaw',
    sample_rate: int = 8000,
    channels: int = 1,
):
    await websocket.accept()
    audio_adapter = STTAudioAdapter(encoding, sample_rate, channels, 16000)

    worker_id = _pool.alloc_job()
    if worker_id < 0:
        print('No workers available, retry later')
        return
    print(f"Successfully allocated worker #{worker_id}")
    
    try:
        while True:
            chunk = await websocket.receive_bytes()
            conv_chunk = audio_adapter.transform(chunk)
            _pool.submit_chunk(worker_id, conv_chunk)
            while not _pool.output_queues[worker_id].empty():
                transcript =_pool.output_queues[worker_id].get()
                print(f"Transcript: {transcript}")
                await websocket.send_bytes(bytes(transcript))
            
    except WebSocketDisconnect:
        _pool.close_job(worker_id)
        print('Disconnected. Bye')