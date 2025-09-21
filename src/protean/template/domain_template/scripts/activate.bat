@echo off
REM Convenience script to activate the virtual environment on Windows
REM Usage: activate.bat

REM Store current directory
set "PREV_DIR=%CD%"

REM Get the directory where this script is located
set "SCRIPT_DIR=%~dp0"

REM Remove trailing backslash
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM Project root is one level up from scripts\
for %%I in ("%SCRIPT_DIR%\..") do set "PROJECT_DIR=%%~fI"

REM Deactivate any current virtual environment
if defined VIRTUAL_ENV (
    echo Deactivating current virtual environment...
    call deactivate 2>nul
)

REM Change to project directory
cd /d "%PROJECT_DIR%"
echo Switched to project directory:
echo   %CD%
echo.

REM Activate virtual environment
if exist "%PROJECT_DIR%\.venv\Scripts\activate.bat" (
    call "%PROJECT_DIR%\.venv\Scripts\activate.bat"
    echo Virtual environment activated!
    echo.
    echo Available commands:
    echo   protean shell  - Start an interactive shell with domain context
    echo   protean test   - Run tests
    echo   protean server - Start the async message processor
    echo.
    echo Other useful commands:
    echo   poetry add ^<package^>     - Add a new dependency
    echo   poetry install          - Install all dependencies
    echo   ruff check              - Check code style
    echo   ruff format             - Format code
    echo   mypy src\{{ package_name }}  - Type check your code
) else (
    echo ERROR: Virtual environment not found at .venv\
    echo.
    echo Please run the following to set up your environment:
    echo   python -m venv .venv
    echo   .venv\Scripts\activate.bat
    echo   pip install poetry
    echo   poetry install --with dev,test,docs,types --all-extras
)