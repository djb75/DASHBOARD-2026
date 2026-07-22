@echo off
REM Double-click launcher for Windows: activates the venv and starts the dashboard.
cd /d "%~dp0"

if not exist ".venv" (
    echo Virtual environment not found. Running setup first...
    call setup.bat
)

call .venv\Scripts\activate.bat

REM Belt-and-suspenders: make sure Streamlit won't block on the first-run email prompt.
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    echo [general] > "%USERPROFILE%\.streamlit\credentials.toml"
    echo email = "" >> "%USERPROFILE%\.streamlit\credentials.toml"
)

streamlit run app.py

echo.
pause
