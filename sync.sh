HOST=${HOST:-ally}
RSYNC="rsync -rv --exclude .git --exclude venv --exclude __pycache__'"
USER=${USER:-bazzite}

# python -m venv --system-site-packages ~/hhd-dev/hhd/venv
# ~/hhd-dev/hhd/venv/bin/pip install -e ~/hhd-dev/hhd
# ~/hhd-dev/hhd/venv/bin/pip install -e ~/hhd-dev/adjustor
# sudo chcon -R -u system_u -r object_r --type=bin_t /var/home/$USER/hhd-dev/hhd/venv/bin

# set -e
$RSYNC . $HOST:hhd-dev/hhd
$RSYNC ../adjustor/ $HOST:hhd-dev/adjustor
$RSYNC ../hhd-bazzite/ $HOST:hhd-dev/hhd-bazzite

ssh $HOST /bin/bash << EOF
    sudo systemctl restart hhdl
EOF

