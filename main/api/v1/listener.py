import asyncio
from threading import Thread, Event
from time import sleep, time
from fastapi import (
    APIRouter,
    Depends,
    Path,
    WebSocket,
    WebSocketDisconnect,
)
from services.stt.audio_adapter import STTAudioAdapter
from services.stt.models_pool import ModelsPool

MAX_CONCURRENT_MODELS = 1

_pool = ModelsPool(MAX_CONCURRENT_MODELS)

#from core.logger import LoggingRoute
from api.security import websocket_api_key_credentials

listener_router = APIRouter(
    prefix="/listen",
    tags=["listener"],
    responses={404: {"description": "Not found"}},
    #route_class=LoggingRoute,
)
     
WEBSOCKET_WRITER_TIMEOUT = 0.1
PAUSE_DETECTION_TIMEOUT = 3.0

def websocket_writer(websocket, model, stop_event):
    print('writer: ready')
    last_transcript = ''
    last_ts = time()
    in_pause = False
    while not stop_event.is_set():
        done, transcript = model.transcribe()
        now = time()
        if not in_pause and now - last_ts > PAUSE_DETECTION_TIMEOUT:
            print('writer: pause detected')
            last_ts = now
            in_pause = True
        if done and transcript != last_transcript:
            last_transcript = transcript
            last_ts = now
            in_pause = False
            print(f'writer: {transcript}')
            #asyncio.run(websocket.send_bytes(bytes(transcript)))
        else:
            sleep(WEBSOCKET_WRITER_TIMEOUT)
    print('writer: shutting down')
        
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
    
    print('websocket: initializing r/w tasks')
    
    writer_stop_event = Event()
    writer_thread = Thread(target=websocket_writer, args=(websocket, _pool.models[worker_id], writer_stop_event))
    writer_thread.start()

    print('reader: ready')
    try:
        while True:
            chunk = await websocket.receive_bytes()
            print(f'reader: received {len(chunk)} bytes')
            conv_chunk = audio_adapter.transform(chunk)
            _pool.submit_chunk(worker_id, conv_chunk)
            
    except WebSocketDisconnect:
        print('reader: websocket closed')
        _pool.close_job(worker_id)
        writer_stop_event.set()
        writer_thread.join()