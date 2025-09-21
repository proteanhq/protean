#!/bin/bash
# Convenience script to activate the virtual environment
# Usage: source activate.sh

# Store current directory
PREV_DIR="$(pwd)"

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# Project root is one level up from scripts/
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Deactivate any current virtual environment
if [ -n "$VIRTUAL_ENV" ]; then
    echo 'Deactivating current virtual environment...'
    deactivate 2>/dev/null || true
fi

# Change to project directory
cd "$PROJECT_DIR"
echo 'Switched to project directory:'
echo "  $(pwd)"
echo ''

# Activate virtual environment
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
    echo '✅ Virtual environment activated!'
    echo ''
    echo '📚 Available commands:'
    echo '  protean shell  - Start an interactive shell with domain context'
    echo '  protean test   - Run tests'
    echo '  protean server - Start the async message processor'
    echo ''
    echo '🔧 Other useful commands:'
    echo '  poetry add <package>     - Add a new dependency'
    echo '  poetry install          - Install all dependencies'
    echo '  ruff check              - Check code style'
    echo '  ruff format             - Format code'
    echo '  mypy src/{{ package_name }}  - Type check your code'
else
    echo '❌ ERROR: Virtual environment not found at .venv/'
    echo ''
    echo 'Please run the following to set up your environment:'
    echo '  python3 -m venv .venv'
    echo '  source .venv/bin/activate'
    echo '  pip install poetry'
    echo '  poetry install --with dev,test,docs,types --all-extras'
fi