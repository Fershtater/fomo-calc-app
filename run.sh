#!/bin/bash
# FarmCalc local development runner

set -e

# Load .env file if it exists
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Check if Poetry is installed
if ! command -v poetry &> /dev/null; then
    echo "Poetry is not installed. Installing..."
    curl -sSL https://install.python-poetry.org | python3 -
    export PATH="$HOME/.local/bin:$PATH"
fi

# Install dependencies if needed
if [ ! -d ".venv" ] && [ -f "poetry.lock" ]; then
    echo "Installing dependencies with Poetry..."
    poetry install
fi

# Run command
case "$1" in
    api)
        echo "Starting FastAPI server..."
        poetry run uvicorn farmcalc.api:app --host 0.0.0.0 --port 8000 --reload
        ;;
    watch)
        echo "Starting watcher..."
        poetry run farmcalc watch --interval 5 --top 25
        ;;
    telegram-poll)
        echo "Starting Telegram polling..."
        poetry run farmcalc telegram poll
        ;;
    *)
        echo "Usage: $0 {api|watch|telegram-poll}"
        echo ""
        echo "  api           - Run FastAPI server"
        echo "  watch         - Run watcher in foreground"
        echo "  telegram-poll - Run Telegram long polling"
        exit 1
        ;;
esac
