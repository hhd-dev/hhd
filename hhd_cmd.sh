#!/usr/bin/bash
# Runs a new handheld daemon version until reboot
sudo systemctl stop hhd@$(whoami)
sudo systemctl stop hhd_local@$(whoami)
sudo pkill hhd

rm -rf ~/.local/share/hhd-tmp
mkdir -p ~/.local/share/hhd-tmp
python -m venv --system-site-packages ~/.local/share/hhd-tmp/venv
~/.local/share/hhd-tmp/venv/bin/pip install git+https://github.com/hhd-dev/adjustor git+https://github.com/hhd-dev/hhd

sudo ~/.local/share/hhd-tmp/venv/bin/hhd --user $(whoami)