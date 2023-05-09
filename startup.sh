#!/bin/sh -e
cd "$(dirname $(realpath $0))"
python3 main.py "$@"
