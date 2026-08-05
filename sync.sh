#!/bin/sh

if [ -z "$1" ]; then
    echo "Usage: $0 <host>"
    exit 1
fi

HOST=$1

# set -e
rsync -rv --exclude .git --exclude venv --exclude __pycache__ . "$HOST:hhd"

ssh -t "$HOST" '
    cd "$HOME/hhd" || exit
    if [ ! -d venv ]; then
        python3 -m venv --system-site-packages venv
        venv/bin/pip install -e .
    fi
    sudo systemctl stop hhd

    exec sudo \
        HHD_HORI_STEAM=1 \
        HHD_HIDE_ALL=1 \
        HHD_BOOTC=1 \
        HHD_ADJUSTOR_NEXT=1 \
        HHD_BOOTC_SOFT_REBOOT=1 \
        HHD_GS_FRAMEGEN=1 \
        "$HOME/hhd/venv/bin/hhd"
'
