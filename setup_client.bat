@echo off
echo ==========================================
echo Starting Setup for Client PC (With GPU Support)...
echo ==========================================

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not added to PATH!
    echo Please install Python (check "Add Python to PATH" during installation^).
    pause
    exit /b
)

echo.
echo [1/5] Checking Environment File...
if not exist .env (
    echo Creating an empty .env file for your API keys...
    copy .env.example .env >nul
) else (
    echo .env file already exists.
)

echo.
echo [2/5] Creating an isolated Python environment (venv)...
python -m venv venv

echo.
echo [2/5] Activating the environment...
call venv\Scripts\activate.bat

echo.
echo [3/5] Installing PyTorch with NVIDIA GPU (CUDA) Support...
:: We install this first so other libraries like ultralytics and easyocr use it.
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

echo.
echo [4/5] Installing remaining project libraries...
pip install -r requirements.txt

echo.
echo ==========================================
echo Setup Complete! GPU support has been configured.
echo You can now double-click "run_app.bat" to start the tool.
echo ==========================================
pause
