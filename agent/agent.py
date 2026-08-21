"""
ObserveX Windows Agent — Collects system metrics and streams them to the centralized server.

Usage:
    python -m agent.agent
    python -m agent.agent --server https://observex.example.com --enroll OX-7F29-A82D
    python -m agent.agent --server http://10.0.0.5:8000
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
from agent.config import agent_settings, save_config, load_config
from agent.sender import AgentSender
from agent.heartbeat import HeartbeatManager
from agent.enrollment import enroll_device, interactive_enrollment


def parse_args():
    parser = argparse.ArgumentParser(description="ObserveX Windows Agent")
    parser.add_argument("--server", type=str, default=None, help="Server URL (overrides config)")
    parser.add_argument("--enroll", type=str, default=None, metavar="CODE", help="Enrollment code for first-time enrollment")
    parser.add_argument("--name", type=str, default=None, help="Device name (overrides config / hostname)")
    parser.add_argument("--interval", type=float, default=None, help="Metric stream interval in seconds")
    # Legacy compat
    parser.add_argument("--key", type=str, default=None, help="API key (legacy, use --enroll instead)")
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

    # Apply CLI overrides to config
    if args.server:
        agent_settings.server.url = args.server
    if args.interval:
        agent_settings.agent.metrics_interval = args.interval
    if args.key:
        agent_settings.device.credential = args.key
    if args.name:
        agent_settings.device.name = args.name

    # ── Enrollment Check ──
    if args.enroll:
        # Explicit enrollment via CLI flag
        server_url = agent_settings.server.url
        await enroll_device(server_url, args.enroll, args.name)
    elif not agent_settings.is_enrolled:
        # Not enrolled and no enrollment code given — try interactive
        print("[Agent] Device is not enrolled with any server.")
        if sys.stdin.isatty():
            success = await interactive_enrollment()
            if not success:
                print("[Agent] Cannot start without enrollment. Exiting.")
                sys.exit(1)
        else:
            # Non-interactive mode (e.g., running as service) — try legacy registration
            print("[Agent] Running in non-interactive mode. Attempting legacy registration...")

    device_name = agent_settings.device.resolved_name
    print(f"\n{'=' * 60}")
    print(f"  ObserveX Agent v{agent_settings.agent.version}")
    print(f"  Device:  {device_name}")
    print(f"  Server:  {agent_settings.server.url}")
    print(f"  Stream:  every {agent_settings.agent.metrics_interval}s")
    print(f"  Enrolled: {'Yes' if agent_settings.is_enrolled else 'No (legacy mode)'}")
    print(f"{'=' * 60}\n")

    print("[Agent] Initializing system monitor...")
    monitor = SystemMonitor()
    await asyncio.sleep(2.0)

    sender = AgentSender()
    heartbeat = HeartbeatManager(sender)

    # Register with exponential backoff (legacy or post-enrollment)
    if not agent_settings.is_enrolled:
        # Legacy registration flow
        backoff = 2.0
        while True:
            try:
                await sender.register(
                    hostname=device_name,
                    os_name=platform.system(),
                    os_version=platform.version(),
                )
                break
            except Exception as e:
                print(f"[Agent] Registration failed ({e}). Retrying in {backoff:.0f}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, agent_settings.network.max_reconnect_backoff)
    else:
        # Enrolled — device_id already set from config
        sender.device_id = agent_settings.device.device_id
        print(f"[Agent] Using enrolled identity: device_id={sender.device_id}")

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
    event_refresh_interval = 300.0
    last_event_refresh = time.time()
    reconnect_backoff = 1.0
    process_tick = 0

    while True:
        if not sender.is_ws_connected:
            if not await sender.connect_ws():
                print(f"[Agent] WebSocket reconnect in {reconnect_backoff:.0f}s...")
                await asyncio.sleep(reconnect_backoff)
                reconnect_backoff = min(
                    reconnect_backoff * 2,
                    agent_settings.network.max_reconnect_backoff,
                )
                continue
            reconnect_backoff = 1.0

        for cmd in await sender.check_incoming_commands():
            if cmd.get("action") == "set_interval":
                agent_settings.agent.metrics_interval = max(0.1, min(60.0, float(cmd.get("value", 1.0))))
                print(f"[Agent] Stream interval updated to {agent_settings.agent.metrics_interval:.1f}s by server")
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

        # Application-level heartbeat
        await heartbeat.tick()

        # Periodic event log refresh
        now = time.time()
        if now - last_event_refresh >= event_refresh_interval:
            last_event_refresh = now
            try:
                await sender.send_event_logs(monitor.get_event_logs(limit=200))
            except Exception as e:
                print(f"[Agent] Event log refresh failed: {e}")

        await asyncio.sleep(agent_settings.agent.metrics_interval)


def main():
    try:
        asyncio.run(run_agent())
    except KeyboardInterrupt:
        print("\n[Agent] Shutting down...")


if __name__ == "__main__":
    main()
