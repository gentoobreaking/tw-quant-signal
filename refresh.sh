#!/bin/bash

#source .venv/bin/activate && pip install -e . -q 2>&1 | tail -2
#source .venv/bin/activate && python -c "from tw_quant_signal.config import settings"

# 若要重新回填歷史資料：
source .venv/bin/activate && python -m tw_quant_signal.backfill
