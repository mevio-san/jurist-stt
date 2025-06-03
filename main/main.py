import uvicorn
from fastapi import FastAPI
from api.v1.rest import v1_router
from fastapi.middleware.cors import CORSMiddleware
import numpy as np

# app
app = FastAPI()
api = FastAPI()

origins = [
    'http://localhost:3000',
    'http://localhost:5173',
    'http://127.0.0.1:3000',
    'http://127.0.0.1:5173',
    # add the final origin here
]

# CORS
api.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET"],
    allow_headers=["Access-Control-Allow-Headers", 'Content-Type', 'Authorization', 'Access-Control-Allow-Origin'],
    expose_headers=["*"],
    allow_credentials=True,
)

# versioning router
api.include_router(v1_router)

app.mount("/api", api)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
