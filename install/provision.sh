#!/usr/bin/env bash
# Launcher for install/provision.py. Run this on a fresh Ubuntu Server:
#     bash install/provision.sh            (add --help to see the options)
#
# The install takes a while, so on a real run this reopens itself inside tmux: if your SSH connection drops, the install
# keeps going, and `tmux attach -t fs42-setup` brings you back to it. Everything printed is also kept in ~/fs42-setup.log.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
    echo "Installing python3 first..."
    sudo apt-get update && sudo apt-get install -y python3
fi

dry=0
for arg in "$@"; do [ "$arg" = "--dry-run" ] && dry=1; [ "$arg" = "--help" ] || [ "$arg" = "-h" ] && dry=1; done

if [ -z "$TMUX" ] && [ -t 0 ] && [ "$dry" -eq 0 ] && [ "$FS42_NO_TMUX" != "1" ]; then
    command -v tmux >/dev/null 2>&1 || { sudo apt-get update && sudo apt-get install -y tmux; }
    printf -v quoted '%q ' "$@"
    exec tmux new-session -A -s fs42-setup "FS42_NO_TMUX=1 bash '$DIR/provision.sh' $quoted; echo; read -r -p 'Finished (or stopped). Press Enter to close this window. '"
fi

# -u keeps the prompts visible while the output is also being copied to the log
python3 -u "$DIR/provision.py" "$@" 2>&1 | tee -a "$HOME/fs42-setup.log"
exit "${PIPESTATUS[0]}"
