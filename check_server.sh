#!/bin/bash

# Quick server status and restart script
echo "🏥 Medical Rota Manager - Server Status Check"
echo "=============================================="

# Check if server is running
if curl -s http://localhost:8000/docs > /dev/null 2>&1; then
    echo "✅ Server is running on port 8000"
    echo "📊 API Documentation: http://localhost:8000/docs"
    echo "🏥 Medical Rota UI: http://localhost:8000/static/medical_rota_ui.html"
    
    # Show server process
    SERVER_PID=$(pgrep -f "uvicorn app.main:app")
    if [ ! -z "$SERVER_PID" ]; then
        echo "🔧 Server PID: $SERVER_PID"
    fi
else
    echo "❌ Server is not running"
    echo ""
    read -p "Would you like to start the server? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "🚀 Starting server..."
        ./start_dev_server.sh
    else
        echo "💡 To start manually, run: ./start_dev_server.sh"
    fi
fi