#!/usr/bin/bash
# Runs a new handheld daemon version until reboot
sudo systemctl stop hhd@$(whoami)
sudo systemctl stop hhd_local@$(whoami)
sudo pkill hhd

rm -rf ~/.local/share/hhd-tmp
mkdir -p ~/.local/share/hhd-tmp
python -m venv --system-site-packages ~/.local/share/hhd-tmp/venv
~/.local/share/hhd-tmp/venv/bin/pip install git+https://github.com/hhd-dev/adjustor git+https://github.com/hhd-dev/hhd

FINAL_URL='https://api.github.com/repos/hhd-dev/hhd-ui/releases/latest'
curl -L $(curl -s "${FINAL_URL}" | grep "browser_download_url" | cut -d '"' -f 4) -o $HOME/.local/share/hhd-tmp/hhd-ui
chmod +x $HOME/.local/share/hhd-tmp/hhd-ui

nohup sudo HHD_OVERLAY="$HOME/.local/share/hhd-tmp/hhd-ui" ~/.local/share/hhd-tmp/venv/bin/hhd --user $(whoami) &> /dev/null &