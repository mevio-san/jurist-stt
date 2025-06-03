#!/bin/sh

folder=$(dirname $0)
cd "$folder/main"
if [ -d "../env" ]
then
    ../env/bin/uvicorn --host 0.0.0.0 --reload --log-level debug --workers 3 --port 8000 --proxy-headers main:app
else
    uvicorn --host 0.0.0.0 --reload --log-level debug --workers 3 --port 8000 --proxy-headers main:app
fi
