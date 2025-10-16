#!/bin/bash

# Medical Rota Manager - Development Server Startup Script
echo "🏥 Starting Medical Rota Manager Development Server..."

# Kill any existing server processes
echo "🔄 Cleaning up existing processes..."
pkill -f "uvicorn app.main:app" || true
sleep 2

# Start the FastAPI server in the background
echo "🚀 Starting FastAPI server on port 8000..."
cd /workspaces/Rota-manager
nohup uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 > server.log 2>&1 &

# Wait for server to start and check multiple times
echo "⏳ Waiting for server to start..."
for i in {1..10}; do
    sleep 1
    if curl -s http://localhost:8000/docs > /dev/null 2>&1; then
        break
    fi
    echo "  Attempt $i/10..."
done

# Check if server is running
if curl -s http://localhost:8000/docs > /dev/null 2>&1; then
    echo "✅ Server started successfully!"
    echo "📊 API Documentation: http://localhost:8000/docs"
    echo "🏥 Medical Rota UI: http://localhost:8000/static/medical_rota_ui.html"
    echo "📋 Server logs: tail -f /workspaces/Rota-manager/server.log"
else
    echo "❌ Server failed to start. Check server.log for details."
fi