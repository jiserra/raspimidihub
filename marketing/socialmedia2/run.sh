#!/bin/bash
while true; do date; /home/dk/develop/raspimidihub/marketing/socialmedia2/.venv/bin/python -m announce.dispatch; sleep 1800; done
