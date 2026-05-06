@echo off
REM Event Intelligence System - Windows one-click launcher
REM Usage: double-click or run from cmd: scripts\run.bat

setlocal
cd /d %~dp0\..\backend

echo ============================================================
echo  Event Intelligence System
echo ============================================================

echo [1/3] Installing Python dependencies...
pip install -q -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies. Check your Python / pip.
    exit /b 1
)

echo [2/3] Building embeddings cache (skip if already exists)...
if not exist data\embeddings.npz (
    python scripts\build_embeddings.py
    if errorlevel 1 (
        echo [WARN] Embedding build failed, will fall back at runtime.
    )
) else (
    echo       embeddings.npz already present, skipping.
)

echo [3/3] Starting server at http://localhost:8000
echo       Press Ctrl+C to stop.
uvicorn main:app --reload --port 8000

endlocal
