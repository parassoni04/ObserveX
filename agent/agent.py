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
import re
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
    return parser.parse_args()


# ── Remediation Command Execution ──

_ALLOWED_AGENT_ACTIONS = {"restart_service", "kill_process", "cleanup_temp"}
_SAFE_TARGET_REGEX = re.compile(r"^[a-zA-Z0-9_.\- ]{1,128}$")


def execute_remediation_command(cmd: dict) -> tuple[str, str]:
    """
    Execute a remediation command from the server.

    Returns:
        (status, output) — "success"/"failed" and a description string.

    Security:
        - Agent-side allowlist prevents arbitrary command execution.
        - Target parameter is regex-validated against injection.
    """
    action = cmd.get("action")
    target = cmd.get("target")

    # Defense in depth: validate against agent-side allowlist
    if action not in _ALLOWED_AGENT_ACTIONS:
        msg = f"Rejected unpermitted command: {action}"
        print(f"[Agent Security] {msg}")
        return "failed", msg

    # Validate target parameter if provided
    if target is not None:
        target = str(target).strip()
        if not _SAFE_TARGET_REGEX.match(target):
            msg = f"Rejected unsafe target parameter: {target}"
            print(f"[Agent Security] {msg}")
            return "failed", msg

    print(f"[Agent Action] Executing remediation: {action} (target={target})")
    try:
        if action == "restart_service" and target:
            subprocess.run(["net", "stop", target], capture_output=True, text=True, timeout=15, check=False)
            res = subprocess.run(["net", "start", target], capture_output=True, text=True, timeout=15, check=False)
            output = f"Service '{target}' restart: {res.stdout.strip()}"
            print(f"[Agent Action] {output}")
            return "success", output

        elif action == "kill_process" and target:
            import psutil
            killed = 0
            for p in psutil.process_iter(['pid', 'name']):
                try:
                    if p.info['name'] and target.lower() in p.info['name'].lower():
                        p.kill()
                        killed += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            output = f"Terminated {killed} instances of '{target}'"
            print(f"[Agent Action] {output}")
            return "success", output

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
            output = f"Cleaned up {cleared} temp files in {temp_dir}"
            print(f"[Agent Action] {output}")
            return "success", output

        return "failed", f"Unhandled action: {action}"

    except Exception as e:
        msg = f"Failed to execute {action}: {e}"
        print(f"[Agent Action] {msg}")
        return "failed", msg


async def run_agent():
    args = parse_args()

    # Apply CLI overrides to config
    if args.server:
        agent_settings.server.url = args.server
    if args.interval:
        agent_settings.agent.metrics_interval = args.interval
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
            # Non-interactive mode — cannot proceed without enrollment
            print("[Agent] Not enrolled and running non-interactively. Exiting.")
            print("[Agent] Enroll first: python -m agent.agent --server <URL> --enroll <CODE>")
            sys.exit(1)

    device_name = agent_settings.device.resolved_name
    print(f"\n{'=' * 60}")
    print(f"  ObserveX Agent v{agent_settings.agent.version}")
    print(f"  Device:  {device_name}")
    print(f"  Server:  {agent_settings.server.url}")
    print(f"  Stream:  every {agent_settings.agent.metrics_interval}s")
    print(f"  Device ID: {agent_settings.device.device_id}")
    print(f"{'=' * 60}\n")

    print("[Agent] Initializing system monitor...")
    monitor = SystemMonitor()
    await asyncio.sleep(2.0)

    sender = AgentSender()
    sender.device_id = agent_settings.device.device_id
    heartbeat = HeartbeatManager(sender)
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
            if "403" in str(e):
                print(f"[Agent] [WARNING] Server rejected credentials for device_id={sender.device_id} (403 Forbidden).")
                print(f"[Agent] [INFO] The device is not recognized by the server. Re-enroll this machine with:")
                print(f"[Agent]    .\\ObserveXAgent.exe --enroll <CODE>")
                print(f"[Agent]    or: python -m agent.agent --enroll <CODE>")
            else:
                print(f"[Agent] Failed to upload {label}: {e}")

    print("[Agent] Starting metric stream...")
    event_refresh_interval = 300.0
    last_event_refresh = time.time()
    reconnect_backoff = 1.0
    process_tick = 0

    while True:
        if not sender.is_ws_connected:
            if not await sender.connect_ws():
                if getattr(sender, "auth_rejected", False):
                    print(f"\n[Agent] [ERROR] Server rejected device authentication (device_id={sender.device_id}).")
                    print(f"[Agent] [INFO] The device credentials are invalid or this device is not registered in the server database.")
                    print(f"[Agent] [INFO] Please re-enroll this device with an enrollment code from the ObserveX dashboard:")
                    print(f"[Agent]    .\\ObserveXAgent.exe --enroll <ENROLLMENT_CODE>")
                    print(f"[Agent]    or: python -m agent.agent --enroll <ENROLLMENT_CODE>\n")
                    sys.exit(1)

                print(f"[Agent] WebSocket reconnect in {reconnect_backoff:.0f}s...")
                await asyncio.sleep(reconnect_backoff)
                reconnect_backoff = min(
                    reconnect_backoff * 2,
                    agent_settings.network.max_reconnect_backoff,
                )
                continue
            reconnect_backoff = 1.0

        # Process incoming commands
        for cmd in await sender.check_incoming_commands():
            cmd_id = cmd.get("command_id")
            status, output = execute_remediation_command(cmd)
            # Report result back to server
            if cmd_id:
                await sender.send_command_result(cmd_id, status, output)

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

        # WebSocket-level heartbeat
        await sender.send_ws_heartbeat()

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
