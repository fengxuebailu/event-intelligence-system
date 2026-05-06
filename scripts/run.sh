#!/usr/bin/env bash
# Event Intelligence System - Linux/macOS one-click launcher
# Usage: bash scripts/run.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/../backend"

echo "============================================================"
echo " Event Intelligence System"
echo "============================================================"

echo "[1/3] Installing Python dependencies..."
pip install -q -r requirements.txt

echo "[2/3] Building embeddings cache (skip if already exists)..."
if [ ! -f "data/embeddings.npz" ]; then
    python scripts/build_embeddings.py || echo "[WARN] embedding build failed, will fall back at runtime."
else
    echo "      embeddings.npz already present, skipping."
fi

echo "[3/3] Starting server at http://localhost:8000"
echo "      Press Ctrl+C to stop."
exec uvicorn main:app --reload --port 8000
