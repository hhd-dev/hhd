#!/usr/bin/bash
# Removes handheld daemon from ~/.local/share/hhd

if [ "$EUID" -eq 0 ]
  then echo "You should run this script as your user, not root (sudo)."
  exit
fi

# Disable Service
sudo systemctl disable --now hhd_local@$(whoami)

# Remove Binary
rm -rf ~/.local/share/hhd

# Remove bin link/overlay
rm -f ~/.local/bin/hhd
rm -f ~/.local/bin/hhd.contrib
rm -f ~/.local/bin/hhd-ui

# Remove /etc files
sudo rm -f /etc/udev/rules.d/83-hhd.rules
sudo rm -f /etc/udev/hwdb.d/83-hhd.hwdb
sudo rm -f /etc/systemd/system/hhd_local@.service

# # Delete your configuration
# rm -rf ~/.config/hhd

echo "Handheld Daemon Uninstalled. Reboot!"