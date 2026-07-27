import os
import sys
import time
import socket
import subprocess
import threading
import uvicorn
import winreg
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from monitor import SystemMonitor

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    global monitor, app_started
    monitor = SystemMonitor()
    app_started = True
    # Start heartbeat checker thread
    threading.Thread(target=heartbeat_watcher, daemon=True).start()
    # Launch browser window after a brief delay
    threading.Thread(target=launch_browser, daemon=True).start()
    yield
    if monitor:
        monitor.stop()

app = FastAPI(title="ObserveX Backend", version="1.0.0", lifespan=lifespan)
monitor = None
last_heartbeat = time.time()
server_port = 8124
app_started = False

# Ensure static files directory exists
os.makedirs("static", exist_ok=True)

class StartupConfig(BaseModel):
    enabled: bool

def get_free_port():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
        s.close()
        return port
    except Exception:
        return 8124

def get_startup_status():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, "ObserveX")
        return True
    except OSError:
        return False

def set_startup_status(enabled: bool):
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    if enabled:
        script_path = os.path.abspath(sys.argv[0])
        python_exe = sys.executable
        # Try to use pythonw.exe so no console is shown on startup
        pythonw_exe = python_exe.replace("python.exe", "pythonw.exe")
        if not os.path.exists(pythonw_exe):
            pythonw_exe = python_exe
        cmd = f'"{pythonw_exe}" "{script_path}"'
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, "ObserveX", 0, winreg.REG_SZ, cmd)
        except OSError as e:
            print(f"Error setting startup registry: {e}")
    else:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
            winreg.DeleteValue(key, "ObserveX")
        except OSError:
            pass



@app.middleware("http")
async def update_heartbeat_middleware(request, call_next):
    global last_heartbeat
    last_heartbeat = time.time()
    return await call_next(request)


@app.get("/api/heartbeat")
def heartbeat_get():
    global last_heartbeat
    last_heartbeat = time.time()
    return {"status": "ok"}

@app.post("/api/heartbeat")
def heartbeat_post():
    global last_heartbeat
    last_heartbeat = time.time()
    return {"status": "ok"}


@app.get("/")
def read_root():
    index_path = os.path.join("static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "ObserveX Frontend not built yet. Please place index.html in the static folder."}

@app.get("/api/static-info")
def get_static_info():
    return monitor.static_info if monitor else {}

@app.get("/api/software")
def get_software():
    return monitor.installed_software if monitor else []

@app.get("/api/updates")
def get_updates():
    if not monitor:
        return {}
    return {
        "history": monitor.update_history,
        "pending": monitor.pending_updates,
        "fetching": monitor.is_fetching_updates
    }

@app.post("/api/updates/refresh")
def refresh_updates():
    if monitor:
        threading.Thread(target=monitor.refresh_windows_updates, daemon=True).start()
        return {"status": "refreshing"}
    return {"status": "error", "message": "monitor not initialized"}

@app.get("/api/event-logs")
def get_event_logs(limit: int = 1000):
    return monitor.get_event_logs(limit) if monitor else []

@app.get("/api/processes")
def get_processes():
    return monitor.get_process_list() if monitor else []



@app.get("/api/startup")
def get_startup():
    return {"enabled": get_startup_status()}

@app.post("/api/startup")
def set_startup(config: StartupConfig):
    set_startup_status(config.enabled)
    return {"status": "ok", "enabled": config.enabled}

@app.websocket("/ws/metrics")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    refresh_interval = 1.0  # default 1 second
    
    # Read messages in background to update configs or refresh intervals
    async def receive_configs():
        nonlocal refresh_interval
        try:
            while True:
                data = await websocket.receive_json()
                if data.get("action") == "set_interval":
                    val = float(data.get("value", 1.0))
                    refresh_interval = max(0.1, min(60.0, val))
        except Exception:
            pass

    config_task = threading.Thread(target=None) # We can handle with normal loop and try-except
    # Instead, we just read with non-blocking checks or standard try-except
    
    # To keep it simple and robust, let's create a task to listen to messages
    import asyncio
    async def read_ws_messages():
        nonlocal refresh_interval
        try:
            while True:
                data = await websocket.receive_json()
                if data.get("action") == "set_interval":
                    val = float(data.get("value", 1.0))
                    refresh_interval = max(0.1, val)
                    if monitor:
                        monitor.refresh_interval = refresh_interval
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    msg_task = asyncio.create_task(read_ws_messages())

    try:
        while True:
            if monitor:
                metrics = monitor.get_live_metrics()
                await websocket.send_json(metrics)
            await asyncio.sleep(refresh_interval)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WS error: {e}")
    finally:
        msg_task.cancel()

def heartbeat_watcher():
    if "--no-shutdown" in sys.argv:
        print("ObserveX: Heartbeat watcher disabled via --no-shutdown CLI option.")
        return
    # Allow 30 seconds for initial connection
    time.sleep(30.0)
    while True:
        # Check last heartbeat. If closed, exit.
        if time.time() - last_heartbeat > 12.0:
            print("ObserveX: No heartbeat received from frontend for 12 seconds. Shutting down system server.")
            os._exit(0)
        time.sleep(1.0)

def find_edge_path():
    # 1. Try registry App Paths
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe", 0, winreg.KEY_READ)
        path = winreg.QueryValue(key, "")
        if os.path.exists(path):
            return path
    except OSError:
        pass
        
    # 2. Try standard installation paths
    paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe")
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None

def launch_browser():
    # Wait a second for uvicorn to boot up
    time.sleep(1.2)
    url = f"http://127.0.0.1:{server_port}"
    edge_path = find_edge_path()
    
    if edge_path:
        print(f"ObserveX: Launching standalone Edge dashboard window using: {edge_path} for {url}")
        try:
            # Launch Microsoft Edge in App Mode (which hides browser frames)
            subprocess.Popen([edge_path, f"--app={url}"])
            return
        except Exception as e:
            print(f"Failed to launch Edge via absolute path: {e}")
            
    print("ObserveX: Falling back to default web browser.")
    import webbrowser
    webbrowser.open(url)

# Mount static files (mount this last so it doesn't shadow / endpoint)
app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    server_port = get_free_port()
    print(f"ObserveX: Starting local web server on port {server_port}")
    uvicorn.run(app, host="127.0.0.1", port=server_port, log_level="warning")
