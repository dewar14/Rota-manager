# 🏥 Medical Rota Manager - Development Scripts

## 🚀 Quick Start Commands

### Start/Restart Server
```bash
./start_dev_server.sh
```

### Check Server Status  
```bash
./check_server.sh
```

### Access Application
- **API Documentation**: http://localhost:8000/docs
- **Medical Rota UI**: http://localhost:8000/static/medical_rota_ui.html

## 🔧 VS Code Tasks

Press `Ctrl+Shift+P` and type "Tasks: Run Task" to access:

- **Restart Server** - Kills and restarts the development server
- **Check Server Status** - Quick status check
- **Run API** - Standard uvicorn start (foreground)
- **PyTest** - Run tests

## 🔄 Auto-Restart on Codespace Open

The server will automatically start when you open this Codespace thanks to the `.devcontainer/devcontainer.json` configuration.

## 🛠️ Troubleshooting

### Server Not Responding
1. Run `./check_server.sh` to see current status
2. If needed, run `./start_dev_server.sh` to restart
3. Check `server.log` for detailed error messages

### Port Issues
If port 8000 is busy:
```bash
# Kill processes on port 8000
sudo lsof -ti:8000 | xargs kill -9
./start_dev_server.sh
```

### Clean Restart
```bash
# Clean restart with log cleanup
rm -f server.log
./start_dev_server.sh
```