#!/usr/bin/bash
# Installs Handheld Daemon to ~/.local/share/hhd

if [ "$EUID" = 0 ]; then 
  echo "You should run this script as your user, not root (sudo)."
  exit
fi

is_bazzite=$(cat /etc/os-release  | sed -e 's/\(.*\)/\L\1/' | grep bazzite-deck)
if [ "${is_bazzite}" ]; then
  echo "Handheld Daemon is preinstalled on bazzite-deck."
  echo "If your device is not whitelisted, you can enable Handheld Daemon with the command:"
  echo "sudo systemctl enable --now hhd@\$(whoami)"
  exit
fi

is_steamos=$(cat /etc/os-release  | grep ID=steamos)
if [[ -n "${is_steamos}" && -z "${BYPASS_STEAMOS_CHECK}" ]]; then
  echo "Installing Handheld Daemon on SteamOS is not canon."
  echo
  echo "Did you mean to install Bazzite? https://bazzite.gg"
  exit
fi

set -e

# Install Handheld Daemon to ~/.local/share/hhd
mkdir -p ~/.local/share/hhd && cd ~/.local/share/hhd

python3 -m venv --system-site-packages venv
source venv/bin/activate
pip3 install --upgrade hhd adjustor

# Install udev rules and create a service file
sudo mkdir -p /etc/udev/rules.d/
sudo mkdir -p /etc/udev/hwdb.d/
sudo curl https://raw.githubusercontent.com/hhd-dev/hhd/master/usr/lib/udev/rules.d/83-hhd.rules -o /etc/udev/rules.d/83-hhd.rules
sudo curl https://raw.githubusercontent.com/hhd-dev/hhd/master/usr/lib/udev/hwdb.d/83-hhd.hwdb -o /etc/udev/hwdb.d/83-hhd.hwdb
sudo curl https://raw.githubusercontent.com/hhd-dev/hhd/master/usr/lib/systemd/system/hhd_local%40.service -o /etc/systemd/system/hhd_local@.service

# Add hhd to user path
mkdir -p ~/.local/bin
ln -s ~/.local/share/hhd/venv/bin/hhd ~/.local/bin/hhd
ln -s ~/.local/share/hhd/venv/bin/hhd.contrib ~/.local/bin/hhd.contrib

FINAL_URL='https://api.github.com/repos/hhd-dev/hhd-ui/releases/latest'
curl -L $(curl -s "${FINAL_URL}" | grep "browser_download_url" | cut -d '"' -f 4) -o $HOME/.local/bin/hhd-ui
chmod +x $HOME/.local/bin/hhd-ui

# Start service and reboot
sudo systemctl enable --now hhd_local@$(whoami)

echo ""
echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
echo "!!! Do not forget to remove a Bundled Handheld Daemon if your distro preinstalls it. !!!"
echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
echo ""
echo "Reboot!"
