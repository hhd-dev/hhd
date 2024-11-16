if [ -z "$1" ]; then
    echo "Usage: $0 <host>"
    exit 1
fi

HOST=$1
RSYNC="rsync -rv --exclude .git --exclude venv --exclude __pycache__'"
USER=${USER:-bazzite}

# python -m venv --system-site-packages ~/hhd-dev/hhd/venv
# ~/hhd-dev/hhd/venv/bin/pip install -e ~/hhd-dev/hhd
# ~/hhd-dev/hhd/venv/bin/pip install -e ~/hhd-dev/adjustor
# sudo chcon -R -u system_u -r object_r --type=bin_t /var/home/$USER/hhd-dev/hhd/venv/bin
# sudo systemctl disable --now hhd@$(whoami)
# sudo systemctl mask hhd@$(whoami)
# sudo systemctl enable --now hhdl

# sudo nano /etc/systemd/system/hhdl.service
# [Unit]
# Description=Handheld Daemon Service

# [Service]
# ExecStart=/home/bazzite/hhd-dev/hhd/venv/bin/hhd --user bazzite
# Nice=-12
# Restart=on-failure
# RestartSec=10
# #Environment="HHD_QAM_KEYBOARD=1"
# Environment="HHD_ALLY_POWERSAVE=1"
# Environment="HHD_HORI_STEAM=1"
# Environment="HHD_PPD_MASK=1"
# Environment="HHD_HIDE_ALL=1"
# Environment="HHD_GS_STEAMUI_HALFHZ=1"
# Environment="HHD_GS_DPMS=1"
# Environment="HHD_GS_STANDBY=1"

# [Install]
# WantedBy=multi-user.target

# set -e
$RSYNC . $HOST:hhd-dev/hhd
$RSYNC ../adjustor/ $HOST:hhd-dev/adjustor
$RSYNC ../hhd-bazzite/ $HOST:hhd-dev/hhd-bazzite

ssh $HOST /bin/bash << EOF
    sudo systemctl restart hhdl
EOF

