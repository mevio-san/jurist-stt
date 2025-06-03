#!/bin/sh

folder=$(dirname $0)
cd "$folder"

python3 -m venv env
. ./env/bin/activate
pip3 install wheel
pip3 install . --force-reinstall