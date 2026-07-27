"""
ObserveX Windows Agent
======================
Collects system metrics using SystemMonitor and streams them
to the centralized ObserveX server.

Usage:
    python -m agent.agent
    python -m agent.agent --server http://10.0.0.5:8000
    python -m agent.agent --key my-secure-key --name MyPC
"""

import sys
import os
import time
import asyncio
import platform
import argparse
import threading

# Ensure project root is on the path so 'monitor' can be imported
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
    """Execute automated IT remediation action on local Windows host."""
    action = cmd.get("action")
    target = cmd.get("target")
    print(f"[Agent Action] Executing remediation: {action} (target={target})")

    try:
        if action == "restart_service" and target:
            subprocess.run(["net", "stop", target], capture_output=True, text=True, timeout=15)
            res = subprocess.run(["net", "start", target], capture_output=True, text=True, timeout=15)
            print(f"[Agent Action] Service '{target}' restart output: {res.stdout.strip()}")
        elif action == "kill_process" and target:
            import psutil
            killed = 0
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if proc.info['name'] and target.lower() in proc.info['name'].lower():
                        proc.kill()
                        killed += 1
                except Exception:
                    pass
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

    # Override settings from CLI args
    if args.server:
        agent_settings.OBSERVEX_SERVER_URL = args.server
    if args.key:
        agent_settings.OBSERVEX_API_KEY = args.key
    if args.interval:
        agent_settings.OBSERVEX_STREAM_INTERVAL = args.interval

    device_name = args.name or agent_settings.device_name

    print("=" * 60)
    print(f"  ObserveX Agent v2.0.0")
    print(f"  Device:  {device_name}")
    print(f"  Server:  {agent_settings.OBSERVEX_SERVER_URL}")
    print(f"  Stream:  every {agent_settings.OBSERVEX_STREAM_INTERVAL}s")
    print("=" * 60)

    # Initialize the system monitor
    print("[Agent] Initializing system monitor...")
    monitor = SystemMonitor()

    await asyncio.sleep(2.0)

    sender = AgentSender()

    registered = False
    backoff = 2.0
    while not registered:
        try:
            await sender.register(
                hostname=device_name,
                os_name=platform.system(),
                os_version=platform.version(),
            )
            registered = True
        except Exception as e:
            print(f"[Agent] Registration failed ({e}). Retrying in {backoff:.0f}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    try:
        await sender.send_static_info(monitor.static_info)
    except Exception as e:
        print(f"[Agent] Failed to upload static info: {e}")

    try:
        await sender.send_software_list(monitor.installed_software)
    except Exception as e:
        print(f"[Agent] Failed to upload software list: {e}")

    try:
        events = monitor.get_event_logs(limit=200)
        await sender.send_event_logs(events)
    except Exception as e:
        print(f"[Agent] Failed to upload event logs: {e}")

    print("[Agent] Starting metric stream...")

    heartbeat_interval = 10.0
    event_refresh_interval = 300.0
    last_heartbeat = time.time()
    last_event_refresh = time.time()
    reconnect_backoff = 1.0
    process_tick = 0
    process_send_interval = 5

    while True:
        if not sender.is_ws_connected:
            connected = await sender.connect_ws()
            if not connected:
                print(f"[Agent] WebSocket reconnect in {reconnect_backoff:.0f}s...")
                await asyncio.sleep(reconnect_backoff)
                reconnect_backoff = min(reconnect_backoff * 2, 30.0)
                continue
            reconnect_backoff = 1.0

        # Check for incoming remote automation commands from server
        cmds = await sender.check_incoming_commands()
        for cmd in cmds:
            execute_remediation_command(cmd)

        metrics = monitor.get_live_metrics()

        process_tick += 1
        if process_tick >= process_send_interval:
            process_tick = 0
            try:
                metrics["processes"] = monitor.get_process_list()
            except Exception:
                pass

        sent = await sender.send_metrics(metrics)
        if not sent:
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
                events = monitor.get_event_logs(limit=200)
                await sender.send_event_logs(events)
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
