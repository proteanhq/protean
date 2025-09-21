#!/usr/bin/env fish
# Convenience script to activate the virtual environment for fish shell
# Usage: source activate.fish

# Store current directory
set PREV_DIR (pwd)

# Get the directory where this script is located
set SCRIPT_DIR (dirname (status -f))
# Project root is one level up from scripts/
set PROJECT_DIR (dirname $SCRIPT_DIR)

# Deactivate any current virtual environment
if set -q VIRTUAL_ENV
    echo 'Deactivating current virtual environment...'
    deactivate 2>/dev/null; or true
end

# Change to project directory
cd $PROJECT_DIR
echo 'Switched to project directory:'
echo "  "(pwd)

# Check if .venv exists
if not test -d $PROJECT_DIR/.venv
    echo 'Creating virtual environment...'
    python3 -m venv $PROJECT_DIR/.venv

    # Install Poetry in the virtual environment
    echo 'Installing Poetry...'
    $PROJECT_DIR/.venv/bin/pip install --upgrade pip setuptools wheel >/dev/null 2>&1
    $PROJECT_DIR/.venv/bin/pip install poetry >/dev/null 2>&1

    # Install dependencies
    echo 'Installing dependencies...'
    set -x VIRTUAL_ENV $PROJECT_DIR/.venv
    $PROJECT_DIR/.venv/bin/poetry install --with dev,test,docs,types --all-extras

    # Install pre-commit hooks
    if test -d $PROJECT_DIR/.git
        echo 'Installing pre-commit hooks...'
        $PROJECT_DIR/.venv/bin/pre-commit install >/dev/null 2>&1
    end
end

# Activate the virtual environment
echo 'Activating virtual environment...'
source $PROJECT_DIR/.venv/bin/activate.fish

echo ''
echo '✅ Environment ready!'
echo ''
echo 'You can now use:'
echo '  protean shell   - Interactive shell with domain context'
echo '  protean test    - Run tests'
echo '  protean server  - Start the async message processing server'
echo ''
echo 'To return to your previous directory, run:'
echo "  cd $PREV_DIR"