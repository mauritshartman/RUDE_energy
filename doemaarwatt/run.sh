#!/bin/bash

echo -e "Contents of /:"
ls -l /
echo -e "Contents of /src:"
ls -l /src
echo -e "Contents of /src/web:"
ls -l /src/web
echo -e "Contents of /src/web/dist:"
ls -l /src/web/dist

python3 -u /src/main.py
