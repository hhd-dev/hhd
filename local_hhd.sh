#!/usr/bin/bash
# Runs a new handheld daemon version until reboot
sudo systemctl stop hhd@$(whoami)
sudo pkill hhd

rm -rf ~/.local/share/hhd
mkdir -p ~/.local/share/hhd
python -m venv --system-site-packages ~/.local/share/hhd/venv
~/.local/share/hhd/venv/bin/pip install git+https://github.com/hhd-dev/adjustor git+https://github.com/hhd-dev/hhd

FINAL_URL='https://api.github.com/repos/hhd-dev/hhd-ui/releases/latest'
curl -L $(curl -s "${FINAL_URL}" | grep "browser_download_url" | cut -d '"' -f 4) -o $HOME/.local/share/hhd/hhd-ui
chmod +x $HOME/.local/share/hhd/hhd-ui

nohup sudo HHD_OVERLAY="$HOME/.local/share/hhd/hhd-ui" ~/.local/share/hhd/venv/bin/hhd --user $(whoami) &> /dev/null &