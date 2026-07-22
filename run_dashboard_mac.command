#!/bin/bash
# Double-click launcher for macOS: activates the venv and starts the dashboard.
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Running setup first..."
    ./setup.sh
fi

source .venv/bin/activate

# Belt-and-suspenders: make sure Streamlit won't block on the first-run email prompt.
mkdir -p ~/.streamlit
if [ ! -f ~/.streamlit/credentials.toml ]; then
    printf '[general]\nemail = ""\n' > ~/.streamlit/credentials.toml
fi

streamlit run app.py

echo
read -p "Dashboard stopped. Press enter to close this window..."
