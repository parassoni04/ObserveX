"""
ObserveX Agent — Build Script.

Builds the agent as a standalone executable using PyInstaller.
Works on Windows, macOS, and Linux.

Usage:
    python agent/build.py              # Build the agent executable
    python agent/build.py --onefile    # Single-file executable
    python agent/build.py --clean      # Clean build artifacts first
"""
import os
import sys
import shutil
import subprocess
import argparse


def get_platform_name() -> str:
    if sys.platform == "win32":
        return "windows"
    elif sys.platform == "darwin":
        return "macos"
    return "linux"


def build_agent(onefile: bool = False, clean: bool = False):
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    agent_entry = os.path.join(project_root, "agent", "agent.py")
    monitor_path = os.path.join(project_root, "monitor.py")
    config_template = os.path.join(project_root, "agent", "config.yaml")
    build_dir = os.path.join(project_root, "build")
    dist_dir = os.path.join(project_root, "dist")

    if clean:
        for d in [build_dir, dist_dir]:
            if os.path.exists(d):
                shutil.rmtree(d)
                print(f"[Build] Cleaned {d}")

    # Determine platform-specific hidden imports
    hidden_imports = [
        "psutil",
        "yaml",
        "pydantic",
        "httpx",
        "websockets",
        "agent",
        "agent.config",
        "agent.sender",
        "agent.enrollment",
        "agent.heartbeat",
    ]

    if sys.platform == "win32":
        hidden_imports.extend([
            "win32com",
            "win32com.client",
            "pythoncom",
            "win32evtlog",
            "win32evtlogutil",
            "win32api",
            "win32serviceutil",
            "win32service",
            "win32event",
            "servicemanager",
        ])

    # Build PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "ObserveXAgent",
        "--noconfirm",
        "--clean" if clean else "",
    ]

    if onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    # Add hidden imports
    for hi in hidden_imports:
        cmd.extend(["--hidden-import", hi])

    # Exclude unused heavy packages (ML, scientific, notebook)
    excludes = [
        "torch", "torchvision", "transformers", "tensorflow", "tensorboard",
        "matplotlib", "scipy", "pandas", "IPython", "notebook", "jupyter",
        "streamlit", "cv2", "PIL", "tkinter", "pyarrow", "safetensors",
        "scikit-learn", "sympy", "onnxruntime", "seaborn",
    ]
    for exc in excludes:
        cmd.extend(["--exclude-module", exc])

    # Add data files
    sep = ";" if sys.platform == "win32" else ":"
    cmd.extend(["--add-data", f"{monitor_path}{sep}."])
    if os.path.exists(config_template):
        cmd.extend(["--add-data", f"{config_template}{sep}agent"])

    # Add paths
    cmd.extend(["--paths", project_root])

    # Console mode (agent runs in background, but console useful for debugging)
    cmd.append("--console")

    # Entry point
    cmd.append(agent_entry)

    # Remove empty strings
    cmd = [c for c in cmd if c]

    print(f"[Build] Building ObserveXAgent for {get_platform_name()}...")
    print(f"[Build] Command: {' '.join(cmd)}")

    result = subprocess.run(cmd, cwd=project_root)
    if result.returncode != 0:
        print(f"[Build] [FAILED] Build failed with exit code {result.returncode}")
        sys.exit(1)

    output_dir = dist_dir
    if onefile:
        exe_name = "ObserveXAgent.exe" if sys.platform == "win32" else "ObserveXAgent"
        print(f"\n[Build] [OK] Single-file executable: {os.path.join(output_dir, exe_name)}")
    else:
        print(f"\n[Build] [OK] Output directory: {os.path.join(output_dir, 'ObserveXAgent')}")

    print(f"[Build] Platform: {get_platform_name()}")


def main():
    parser = argparse.ArgumentParser(description="Build ObserveX Agent executable")
    parser.add_argument("--onefile", action="store_true", help="Build as single-file executable")
    parser.add_argument("--clean", action="store_true", help="Clean build artifacts before building")
    args = parser.parse_args()

    # Check PyInstaller is available
    try:
        import PyInstaller
    except ImportError:
        print("[Build] PyInstaller is required. Install it with:")
        print("  pip install pyinstaller")
        sys.exit(1)

    build_agent(onefile=args.onefile, clean=args.clean)


if __name__ == "__main__":
    main()
