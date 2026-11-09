#!/usr/bin/env bash
cd "$(dirname "$0")"

if [ -f ".venv/Scripts/python.exe" ]; then
    ./.venv/Scripts/python.exe main.py
elif [ -f ".venv/bin/python" ]; then
    ./.venv/bin/python main.py
else
    python main.py
fi

