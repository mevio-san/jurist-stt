from fastapi import WebSocket, WebSocketException, status
from functools import wraps
from core.config import config

# TODO: True Bearer scheme

def websocket_api_key_credentials(func):
    @wraps(func)
    async def wrapper(websocket: WebSocket, *args, **kwargs):
        auth_header = websocket.headers.get("Authorization")
        bearer, api_key = auth_header.split(' ')
        if not auth_header or api_key != config.get('stt_api_key'):
            raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
        return await func(websocket, *args, **kwargs)
    return wrapper