import os
import sys
import time
import socket
import threading
import webbrowser
import asyncio
import uvicorn
import winreg
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from contextlib import asynccontextmanager

from monitor import SystemMonitor


@asynccontextmanager
async def lifespan(app: FastAPI):
    global monitor, app_started
    monitor = SystemMonitor()
    app_started = True
    threading.Thread(target=heartbeat_watcher, daemon=True).start()
    threading.Thread(target=lambda: (time.sleep(1.2), webbrowser.open(f"http://127.0.0.1:{server_port}")), daemon=True).start()
    # ponytail: webbrowser.open instead of Edge --app finder. Restore Edge app-mode if kiosk UX matters.
    yield
    if monitor:
        monitor.stop()


app = FastAPI(title="ObserveX Backend", version="1.0.0", lifespan=lifespan)
monitor = None
last_heartbeat = time.time()
server_port = 8124
app_started = False

os.makedirs("static", exist_ok=True)


class StartupConfig(BaseModel):
    enabled: bool


def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def get_startup_status():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, "ObserveX")
        return True
    except OSError:
        return False


def set_startup_status(enabled: bool):
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    if enabled:
        script_path = os.path.abspath(sys.argv[0])
        exe = sys.executable
        pythonw = exe.replace("python.exe", "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = exe
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, "ObserveX", 0, winreg.REG_SZ, f'"{pythonw}" "{script_path}"')
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


@app.api_route("/api/heartbeat", methods=["GET", "POST"])
def heartbeat():
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
    return {"history": monitor.update_history, "pending": monitor.pending_updates, "fetching": monitor.is_fetching_updates}


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
    refresh_interval = 1.0

    async def read_ws_messages():
        nonlocal refresh_interval
        try:
            while True:
                data = await websocket.receive_json()
                if data.get("action") == "set_interval":
                    refresh_interval = max(0.1, float(data.get("value", 1.0)))
                    if monitor:
                        monitor.refresh_interval = refresh_interval
        except (WebSocketDisconnect, Exception):
            pass

    msg_task = asyncio.create_task(read_ws_messages())
    try:
        while True:
            if monitor:
                await websocket.send_json(monitor.get_live_metrics())
            await asyncio.sleep(refresh_interval)
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        msg_task.cancel()


def heartbeat_watcher():
    if "--no-shutdown" in sys.argv:
        print("ObserveX: Heartbeat watcher disabled via --no-shutdown CLI option.")
        return
    time.sleep(30.0)
    while True:
        if time.time() - last_heartbeat > 12.0:
            print("ObserveX: No heartbeat received from frontend for 12 seconds. Shutting down system server.")
            os._exit(0)
        time.sleep(1.0)


app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    server_port = get_free_port()
    print(f"ObserveX: Starting local web server on port {server_port}")
    uvicorn.run(app, host="127.0.0.1", port=server_port, log_level="warning")
