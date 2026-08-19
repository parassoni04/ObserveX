"""
ObserveX Windows Agent — Collects system metrics and streams them to the centralized server.

Usage:
    python -m agent.agent
    python -m agent.agent --server http://10.0.0.5:8000
    python -m agent.agent --key my-secure-key --name MyPC
"""
import sys
import os
import subprocess
import time
import asyncio
import platform
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitor import SystemMonitor
from agent.config import agent_settings
from agent.sender import AgentSender


def parse_args():
    parser = argparse.ArgumentParser(description="ObserveX Windows Agent")
    parser.add_argument("--server", type=str, default=None, help="Server URL (overrides .env)")
    parser.add_argument("--key", type=str, default=None, help="API key (overrides .env)")
    parser.add_argument("--name", type=str, default=None, help="Device name (overrides .env / hostname)")
    parser.add_argument("--interval", type=float, default=None, help="Metric stream interval in seconds")
    return parser.parse_args()


def execute_remediation_command(cmd: dict):
    action, target = cmd.get("action"), cmd.get("target")
    print(f"[Agent Action] Executing remediation: {action} (target={target})")
    try:
        if action == "restart_service" and target:
            subprocess.run(["net", "stop", target], capture_output=True, text=True, timeout=15)
            res = subprocess.run(["net", "start", target], capture_output=True, text=True, timeout=15)
            print(f"[Agent Action] Service '{target}' restart output: {res.stdout.strip()}")
        elif action == "kill_process" and target:
            import psutil
            killed = sum(1 for p in psutil.process_iter(['pid', 'name'])
                         if p.info['name'] and target.lower() in p.info['name'].lower()
                         and (p.kill() or True))
            # ponytail: p.kill() returns None, `or True` makes the comprehension count it
            print(f"[Agent Action] Terminated {killed} instances of process '{target}'")
        elif action == "cleanup_temp":
            temp_dir = os.environ.get("TEMP", r"C:\Windows\Temp")
            cleared = 0
            for root, dirs, files in os.walk(temp_dir):
                for f in files:
                    try:
                        os.remove(os.path.join(root, f))
                        cleared += 1
                    except Exception:
                        pass
            print(f"[Agent Action] Cleaned up {cleared} temp files in {temp_dir}")
    except Exception as e:
        print(f"[Agent Action] Failed to execute {action}: {e}")


async def run_agent():
    args = parse_args()
    if args.server:
        agent_settings.OBSERVEX_SERVER_URL = args.server
    if args.key:
        agent_settings.OBSERVEX_API_KEY = args.key
    if args.interval:
        agent_settings.OBSERVEX_STREAM_INTERVAL = args.interval

    device_name = args.name or agent_settings.device_name
    print(f"{'=' * 60}\n  ObserveX Agent v2.0.0\n  Device:  {device_name}\n  Server:  {agent_settings.OBSERVEX_SERVER_URL}\n  Stream:  every {agent_settings.OBSERVEX_STREAM_INTERVAL}s\n{'=' * 60}")

    print("[Agent] Initializing system monitor...")
    monitor = SystemMonitor()
    await asyncio.sleep(2.0)

    sender = AgentSender()

    # Register with exponential backoff
    backoff = 2.0
    while True:
        try:
            await sender.register(hostname=device_name, os_name=platform.system(), os_version=platform.version())
            break
        except Exception as e:
            print(f"[Agent] Registration failed ({e}). Retrying in {backoff:.0f}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    # Upload initial data
    for label, fn in [
        ("static info", lambda: sender.send_static_info(monitor.static_info)),
        ("software list", lambda: sender.send_software_list(monitor.installed_software)),
        ("event logs", lambda: sender.send_event_logs(monitor.get_event_logs(limit=200))),
    ]:
        try:
            await fn()
        except Exception as e:
            print(f"[Agent] Failed to upload {label}: {e}")

    print("[Agent] Starting metric stream...")
    heartbeat_interval, event_refresh_interval = 10.0, 300.0
    last_heartbeat = last_event_refresh = time.time()
    reconnect_backoff, process_tick = 1.0, 0

    while True:
        if not sender.is_ws_connected:
            if not await sender.connect_ws():
                print(f"[Agent] WebSocket reconnect in {reconnect_backoff:.0f}s...")
                await asyncio.sleep(reconnect_backoff)
                reconnect_backoff = min(reconnect_backoff * 2, 30.0)
                continue
            reconnect_backoff = 1.0

        for cmd in await sender.check_incoming_commands():
            if cmd.get("action") == "set_interval":
                agent_settings.OBSERVEX_STREAM_INTERVAL = max(0.1, min(60.0, float(cmd.get("value", 1.0))))
                print(f"[Agent] Stream interval updated to {agent_settings.OBSERVEX_STREAM_INTERVAL:.1f}s by server")
            else:
                execute_remediation_command(cmd)

        metrics = monitor.get_live_metrics()
        process_tick += 1
        if process_tick >= 5:
            process_tick = 0
            try:
                metrics["processes"] = monitor.get_process_list()
            except Exception:
                pass

        if not await sender.send_metrics(metrics):
            continue

        now = time.time()
        if now - last_heartbeat >= heartbeat_interval:
            last_heartbeat = now
            try:
                await sender.send_heartbeat()
            except Exception as e:
                print(f"[Agent] Heartbeat failed: {e}")

        if now - last_event_refresh >= event_refresh_interval:
            last_event_refresh = now
            try:
                await sender.send_event_logs(monitor.get_event_logs(limit=200))
            except Exception as e:
                print(f"[Agent] Event log refresh failed: {e}")

        await asyncio.sleep(agent_settings.OBSERVEX_STREAM_INTERVAL)


def main():
    try:
        asyncio.run(run_agent())
    except KeyboardInterrupt:
        print("\n[Agent] Shutting down...")


if __name__ == "__main__":
    main()
