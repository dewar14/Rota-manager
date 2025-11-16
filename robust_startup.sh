#!/bin/bash

# Enhanced Medical Rota Manager - Robust Startup Script
echo "🏥 Enhanced Medical Rota Manager Startup"
echo "========================================"

# Function to check if server is running
check_server() {
    curl -s http://localhost:8000/docs > /dev/null 2>&1
}

# Function to start server
start_server() {
    echo "🚀 Starting FastAPI server..."
    cd /workspaces/Rota-manager
    
    # Start server with better process management
    nohup uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 > server.log 2>&1 &
    SERVER_PID=$!
    echo $SERVER_PID > .server_pid
    
    # Wait for server to be ready
    echo "⏳ Waiting for server startup..."
    for i in {1..15}; do
        sleep 2
        if check_server; then
            echo "✅ Server started successfully on PID $SERVER_PID"
            return 0
        fi
        echo "  Attempt $i/15..."
    done
    
    echo "❌ Server failed to start after 30 seconds"
    return 1
}

# Main startup logic
echo "🔍 Checking current server status..."

if check_server; then
    echo "✅ Server already running"
    SERVER_PID=$(pgrep -f "uvicorn app.main:app")
    echo "📊 Server PID: $SERVER_PID"
else
    echo "🔄 Server not running, cleaning up old processes..."
    
    # Kill any existing uvicorn processes
    pkill -f "uvicorn app.main:app" 2>/dev/null || true
    
    # Remove old PID file
    rm -f .server_pid
    
    # Start fresh server
    if start_server; then
        echo "🎉 Startup completed successfully!"
        echo "📊 API Documentation: http://localhost:8000/docs"
        echo "🏥 Medical Rota UI: http://localhost:8000/static/medical_rota_ui.html"
        echo "📋 Server logs: tail -f /workspaces/Rota-manager/server.log"
        echo "🔧 Server PID saved to .server_pid"
    else
        echo "💥 Startup failed - check server.log for details"
        exit 1
    fi
fi

echo "========================================"