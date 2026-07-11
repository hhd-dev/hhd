if [ -z "$1" ]; then
    echo "Usage: $0 <host>"
    exit 1
fi

HOST=$1
RSYNC="rsync -rv --exclude .git --exclude venv --exclude __pycache__'"

# sudo rm -rf ~/hhd-dev/hhd/venv
# python3 -m venv --system-site-packages ~/hhd-dev/hhd/venv
# ~/hhd-dev/hhd/venv/bin/pip install -e ~/hhd-dev/hhd
# sudo chcon -R -u system_u -r object_r --type=bin_t /var/home/$USER/hhd-dev/hhd/venv/bin

# set -e
$RSYNC . $HOST:hhd-dev/hhd

ssh $HOST /bin/bash << EOF
    sudo systemctl stop hhd
EOF

ssh -t $HOST "sudo HHD_HORI_STEAM=1 HHD_HIDE_ALL=1 HHD_BOOTC=1 ~/hhd-dev/hhd/venv/bin/hhd"