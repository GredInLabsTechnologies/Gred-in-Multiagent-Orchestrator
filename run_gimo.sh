#!/bin/bash
# GIMO CLI wrapper with correct token
export ORCH_TOKEN=$(cat tools/gimo_server/.orch_operator_token)
source .venv/Scripts/activate
python gimo.py "$@"
