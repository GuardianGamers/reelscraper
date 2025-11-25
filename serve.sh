#!/bin/bash
# Simple web server to view video stories

# Kill any process using port 8000
echo "🔧 Checking port 8000..."
lsof -ti:8000 | xargs kill -9 2>/dev/null && echo "✅ Port 8000 cleared" || echo "✅ Port 8000 is free"
echo ""

python3 serve.py

