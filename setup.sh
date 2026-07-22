#!/bin/bash
# One-time setup: creates a virtual environment and installs dependencies.
set -e
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate
echo "Installing dependencies..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

# Pre-seed Streamlit's credentials file so first launch doesn't block on an
# interactive "enter your email" prompt.
mkdir -p ~/.streamlit
if [ ! -f ~/.streamlit/credentials.toml ]; then
    printf '[general]\nemail = ""\n' > ~/.streamlit/credentials.toml
fi

echo "Setup complete. Double-click run_dashboard_mac.command to launch the dashboard."
