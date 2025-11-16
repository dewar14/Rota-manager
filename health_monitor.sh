#!/bin/bash

# Server Health Monitor - runs in background to restart server if it crashes
HEALTH_CHECK_INTERVAL=30  # Check every 30 seconds
MAX_RESTART_ATTEMPTS=3
RESTART_ATTEMPTS=0

echo "🏥 Medical Rota Server Health Monitor Started"
echo "Checking server health every ${HEALTH_CHECK_INTERVAL} seconds..."

while true; do
    sleep $HEALTH_CHECK_INTERVAL
    
    # Check if server is responding
    if ! curl -s http://localhost:8000/docs > /dev/null 2>&1; then
        echo "⚠️  Server not responding at $(date)"
        
        # Check if process is still running
        if [ -f .server_pid ] && kill -0 $(cat .server_pid) 2>/dev/null; then
            echo "🔄 Process exists but not responding, restarting..."
        else
            echo "💀 Process died, attempting restart..."
        fi
        
        if [ $RESTART_ATTEMPTS -lt $MAX_RESTART_ATTEMPTS ]; then
            RESTART_ATTEMPTS=$((RESTART_ATTEMPTS + 1))
            echo "🚀 Restart attempt $RESTART_ATTEMPTS/$MAX_RESTART_ATTEMPTS"
            
            # Run the robust startup script
            ./robust_startup.sh
            
            if curl -s http://localhost:8000/docs > /dev/null 2>&1; then
                echo "✅ Server successfully restarted"
                RESTART_ATTEMPTS=0  # Reset counter on success
            fi
        else
            echo "❌ Max restart attempts exceeded, giving up"
            echo "💡 Run './robust_startup.sh' manually to restart"
            break
        fi
    fi
done