#!/bin/sh
sleep 1
cd "${0%/*}"
python3 main.py "$@"
