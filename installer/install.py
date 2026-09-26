"""
ObserveX Agent — Cross-Platform Installer Script.

Handles agent installation, enrollment, and service registration.
Works on Windows, macOS, and Linux.

Usage:
    python installer/install.py --server https://observex.example.com --code OX-7F29-A82D
    python installer/install.py --server https://observex.example.com --code OX-7F29-A82D --name MyPC
    python installer/install.py --uninstall
"""
import os
import sys
import shutil
import asyncio
import platform
import argparse


def get_install_dir() -> str:
    """Get platform-appropriate installation directory."""
    if sys.platform == "win32":
        return os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), "ObserveX Agent")
    elif sys.platform == "darwin":
        return "/usr/local/bin/observex-agent"
    return "/opt/observex-agent"


def get_config_dir() -> str:
    """Get platform-appropriate config directory."""
    if sys.platform == "win32":
        return os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "ObserveX")
    elif sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/ObserveX")
    return "/etc/observex"


def get_log_dir() -> str:
    """Get platform-appropriate log directory."""
    if sys.platform == "win32":
        return os.path.join(get_config_dir(), "logs")
    elif sys.platform == "darwin":
        return os.path.expanduser("~/Library/Logs/ObserveX")
    return "/var/log/observex"


async def install_agent(server_url: str, enrollment_code: str, device_name: str | None = None):
    """Full installation flow: copy files, enroll, configure service."""
    config_dir = get_config_dir()
    log_dir = get_log_dir()

    print(f"\n{'=' * 60}")
    print(f"  ObserveX Agent Installer")
    print(f"  Platform: {platform.system()} {platform.release()}")
    print(f"  Config:   {config_dir}")
    print(f"  Logs:     {log_dir}")
    print(f"{'=' * 60}\n")

    # Create directories
    for d in [config_dir, log_dir]:
        os.makedirs(d, exist_ok=True)
        print(f"[Install] Created directory: {d}")

    # Write initial config
    config_path = os.path.join(config_dir, "config.yaml")

    # Set environment so agent config resolves to system path
    os.environ["OBSERVEX_CONFIG_PATH"] = config_path
    os.environ["OBSERVEX_SERVER_URL"] = server_url

    # Add project root to path for imports
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from agent.config import load_config, save_config, ObserveXAgentSettings, ServerConfig, LoggingConfig
    from agent.enrollment import enroll_device

    # Create initial config
    initial_settings = ObserveXAgentSettings(
        server=ServerConfig(url=server_url),
        logging=LoggingConfig(
            level="INFO",
            file=os.path.join(log_dir, "agent.log"),
        ),
    )
    save_config(initial_settings, config_path=__import__("pathlib").Path(config_path))
    print(f"[Install] Initial config written to {config_path}")

    # Run enrollment
    print(f"\n[Install] Enrolling device with server...")
    try:
        result = await enroll_device(server_url, enrollment_code, device_name)
        print(f"[Install] ✅ Enrollment successful!")
    except Exception as e:
        print(f"[Install] ❌ Enrollment failed: {e}")
        print(f"[Install] The config file has been created at {config_path}")
        print(f"[Install] You can re-run enrollment later with:")
        print(f"           python -m agent.agent --server {server_url} --enroll {enrollment_code}")
        return False

    # Register service (platform-specific)
    print(f"\n[Install] Registering system service...")
    if sys.platform == "win32":
        _register_windows_service()
    elif sys.platform == "linux":
        _register_systemd_service(config_dir)
    elif sys.platform == "darwin":
        _register_launchd_service(config_dir)

    print(f"\n{'=' * 60}")
    print(f"  ✅ Installation Complete!")
    print(f"  Config: {config_path}")
    print(f"  Logs:   {log_dir}")
    print(f"{'=' * 60}\n")
    return True


def _register_windows_service():
    """Register the agent as a Windows service."""
    try:
        import subprocess
        # Use the service.py module
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        service_module = os.path.join(project_root, "agent", "service.py")
        subprocess.run([sys.executable, service_module, "install"], check=True)
        subprocess.run([sys.executable, service_module, "start"], check=False)
        print("[Install] Windows service installed and started.")
    except Exception as e:
        print(f"[Install] Windows service registration failed: {e}")
        print("[Install] You can manually start the agent with: python -m agent.agent")


def _register_systemd_service(config_dir: str):
    """Register the agent as a systemd service (Linux)."""
    service_content = f"""[Unit]
Description=ObserveX Monitoring Agent
After=network.target

[Service]
Type=simple
ExecStart={sys.executable} -m agent.agent
WorkingDirectory={os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}
Environment=OBSERVEX_CONFIG_PATH={config_dir}/config.yaml
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
    service_path = "/etc/systemd/system/observex-agent.service"
    try:
        with open(service_path, "w") as f:
            f.write(service_content)
        os.system("systemctl daemon-reload")
        os.system("systemctl enable observex-agent")
        os.system("systemctl start observex-agent")
        print(f"[Install] systemd service installed at {service_path}")
    except PermissionError:
        print(f"[Install] Permission denied. Run with sudo to install systemd service.")
        print(f"[Install] Service file content:\n{service_content}")


def _register_launchd_service(config_dir: str):
    """Register the agent as a launchd service (macOS)."""
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.observex.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>-m</string>
        <string>agent.agent</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OBSERVEX_CONFIG_PATH</key>
        <string>{config_dir}/config.yaml</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>"""
    plist_path = os.path.expanduser("~/Library/LaunchAgents/com.observex.agent.plist")
    try:
        with open(plist_path, "w") as f:
            f.write(plist_content)
        os.system(f"launchctl load {plist_path}")
        print(f"[Install] launchd service installed at {plist_path}")
    except Exception as e:
        print(f"[Install] launchd registration failed: {e}")


def uninstall_agent():
    """Uninstall the agent: stop service, remove files."""
    print("\n[Uninstall] Stopping and removing ObserveX Agent...\n")

    if sys.platform == "win32":
        try:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            service_module = os.path.join(project_root, "agent", "service.py")
            os.system(f'"{sys.executable}" "{service_module}" stop')
            os.system(f'"{sys.executable}" "{service_module}" remove')
        except Exception:
            pass
    elif sys.platform == "linux":
        os.system("systemctl stop observex-agent 2>/dev/null")
        os.system("systemctl disable observex-agent 2>/dev/null")
        service_path = "/etc/systemd/system/observex-agent.service"
        if os.path.exists(service_path):
            os.remove(service_path)
            os.system("systemctl daemon-reload")
    elif sys.platform == "darwin":
        plist_path = os.path.expanduser("~/Library/LaunchAgents/com.observex.agent.plist")
        os.system(f"launchctl unload {plist_path} 2>/dev/null")
        if os.path.exists(plist_path):
            os.remove(plist_path)

    config_dir = get_config_dir()
    if os.path.exists(config_dir):
        resp = input(f"  Remove config directory ({config_dir})? [y/N]: ").strip().lower()
        if resp == "y":
            shutil.rmtree(config_dir)
            print(f"[Uninstall] Removed {config_dir}")
        else:
            print(f"[Uninstall] Config preserved at {config_dir}")

    print("[Uninstall] ✅ ObserveX Agent uninstalled.")


def main():
    parser = argparse.ArgumentParser(description="ObserveX Agent Installer")
    parser.add_argument("--server", type=str, help="ObserveX server URL")
    parser.add_argument("--code", type=str, help="Enrollment code")
    parser.add_argument("--name", type=str, default=None, help="Device name")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall the agent")
    args = parser.parse_args()

    if args.uninstall:
        uninstall_agent()
        return

    if not args.server or not args.code:
        parser.error("--server and --code are required for installation")

    asyncio.run(install_agent(args.server, args.code, args.name))


if __name__ == "__main__":
    main()
