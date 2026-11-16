#!/usr/bin/env bash
# Run the Claude-vs-Stockfish series on a Linux cloud machine (Ubuntu/Debian). Run once:  bash cloud_setup.sh
# games/ is not in git: copy your games folder over as well (scp -r games user@host:chess_comp/) to keep what was learned.
set -e
sudo apt-get update
sudo apt-get install -y python3-pip tmux nodejs npm curl
if ! sudo apt-get install -y stockfish; then   # no apt package (e.g. a Claude Code cloud session): the official Linux build
  mkdir -p "$HOME/stockfish" && curl -sSL https://github.com/official-stockfish/Stockfish/releases/download/sf_17.1/stockfish-ubuntu-x86-64-avx2.tar | tar x -C "$HOME/stockfish" --strip-components=1
  echo "Stockfish is at $HOME/stockfish/stockfish-ubuntu-x86-64-avx2 - use that path for STOCKFISH= below"
fi
pip3 install --user chess pytest || pip3 install --user --break-system-packages chess pytest
command -v claude >/dev/null || sudo npm install -g @anthropic-ai/claude-code   # the Claude Code CLI that match.py calls
echo
echo "1. Log in once:        claude          (then /login, and quit)"
echo "2. Check everything:   STOCKFISH=/usr/games/stockfish python3 -m pytest -q"
echo "3. Start the series so it keeps running after you disconnect:"
echo "     tmux new -s chess 'STOCKFISH=/usr/games/stockfish python3 series.py 2>&1 | tee -a series.out'"
echo "   Look in again with: tmux attach -t chess      Stop: Ctrl+C (python3 series.py continues where it stopped)"
echo "4. Learn from the games already in games/ without playing:  STOCKFISH=/usr/games/stockfish python3 learn.py distill"
