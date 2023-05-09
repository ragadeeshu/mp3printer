#!/bin/sh -e

[ -x "$(which systemctl)" ] || {
  echo "systemctl not found. Are you not using Systemd?" >&2
  exit 1
}

args=$(getopt -o g:h --long group:,help -- "$@")
eval set -- "$args"

printHelp() {
  echo "Usage: $0 [-h|--help] [-g|--group <GROUP>] [-- <ARGS>]"
  echo
  echo "Install mp3 printer as a system service, running as the current user."
  echo
  echo "Arguments:"
  echo "  -h|--help           Show this help and exit."
  echo "  -g|--group <GROUP>  Run as the specified (by name or id) group, allowing said"
  echo "                      group write access to the STDIN socket (for commands)."
  echo "  -- <ARGS>           Run the service with the specified arguments."
}

dir=$(dirname $(realpath $0))
user=$(id -un)
uid=$(id -u)
group=$(id -gn)
gid=$(id -g)
stdin_mode=0200
while [ -n "$1" ]; do
  case "$1" in
    -g|--group)
      getent=$(getent group $2)
      group=$(echo $getent | cut -f 1 -d:)
      gid=$(echo $getent | cut -f 3 -d:)
      stdin_mode=0220
      shift 2
      ;;
    -h)
      printHelp
      exit 0
      ;;
    --)
      shift
      break
      ;;
    *)
      echo "Unknown option '$1'!" >&2
      printHelp
      exit 1
      ;;
  esac
done

echo "# Will install service file for running mp3 printer with these settings:"
echo "  - Working dir: $dir"
echo "  - User: $user ($uid)"
echo "  - Group: $group ($gid)"
echo "  - Arguments: ${@:-(none)}"
echo
printf "Continue? [y/N] "
read inp
[ "$inp" = "y" -o "$inp" = "Y" ] || exit 1

echo "# Installing service file..."
sudo tee /etc/systemd/system/mp3printer.service > /dev/null << EOF
[Unit]
After=network-online.target
Description=mp3 Printer

[Service]
User=$uid
Group=$gid
WorkingDirectory=$dir
ExecStart=$(which python3) main.py $@
Sockets=mp3printer.socket
StandardInput=socket
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "# Installing STDIN socket file..."
sudo tee /etc/systemd/system/mp3printer.socket > /dev/null << EOF
[Unit]
Description=mp3 Printer STDIN
PartOf=mp3printer.service

[Socket]
ListenFIFO=$dir/service.stdin
Service=mp3printer.service
SocketUser=$uid
SocketGroup=$gid
SocketMode=$stdin_mode
RemoveOnStop=yes
EOF

sudo systemctl daemon-reload
sudo systemctl enable mp3printer.service

echo "# Starting mp3printer service..."
sudo systemctl start mp3printer.service
