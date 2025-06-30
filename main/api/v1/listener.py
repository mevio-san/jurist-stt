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
from services.stt.messages import STTMessageOut
from core.logger import logger

MAX_CONCURRENT_MODELS = 2

_pool = ModelsPool(MAX_CONCURRENT_MODELS)

#from core.logger import LoggingRoute
from api.security import websocket_api_key_credentials

listener_router = APIRouter(
    prefix="/listen",
    tags=["listener"],
    responses={404: {"description": "Not found"}},
    #route_class=LoggingRoute,
)
     
WEBSOCKET_WORKER_TIMEOUT = 0.1
PAUSE_DETECTION_TIMEOUT = 0.5

def websocket_worker(websocket, model, stop_event):
    logger.info('worker: ready')

    last_transcript = ''
    last_ts = time()
    in_pause = False

    is_final, speech_final, text = False, False, ''
    
    while not stop_event.is_set():
        done, transcript = model.transcribe()
        now = time()
        if not in_pause and now - last_ts > PAUSE_DETECTION_TIMEOUT:
            logger.info('worker: pause detected')
            msg = STTMessageOut()
            msg.setTranscript(last_transcript)
            msg.finalizeTranscript()
            asyncio.run(websocket.send_bytes(msg.toJSON().encode('utf8')))
            logger.debug(msg.toJSON())
            
            last_ts = now
            in_pause = True
            model.reset_hyps()
        elif done and transcript != last_transcript:
            msg = STTMessageOut()
            msg.setTranscript(transcript)
            asyncio.run(websocket.send_bytes(msg.toJSON().encode('utf8')))
            
            last_transcript = transcript
            last_ts = now
            in_pause = False
        else:
            sleep(WEBSOCKET_WORKER_TIMEOUT)
    logger.info('worker: shutting down')
        
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
        logger.error("no workers available, retry later")
        await websocket.close(code=1013, reason="no workers available, retry later")
        return

    logger.info(f"successfully allocated worker #{worker_id}")
      
    worker_stop_event = Event()
    worker_thread = Thread(target=websocket_worker, args=(websocket, _pool.models[worker_id], worker_stop_event))
    worker_thread.start()

    try:
        while True:
            chunk = await websocket.receive_bytes()
            conv_chunk = audio_adapter.transform(chunk)
            _pool.submit_chunk(worker_id, conv_chunk)
            
    except WebSocketDisconnect:
        logger.info('websocket closed')
        _pool.close_job(worker_id)
        worker_stop_event.set()
        worker_thread.join()