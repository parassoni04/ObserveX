"""
ObserveX Agent — Windows Service Wrapper.

Runs the ObserveX agent as a Windows background service.
Install:    python agent/service.py install
Start:      python agent/service.py start
Stop:       python agent/service.py stop
Remove:     python agent/service.py remove

Or use:     sc create ObserveXAgent ...
"""
import sys
import os
import asyncio

# Only import Windows service modules on Windows
if sys.platform == "win32":
    try:
        import win32serviceutil
        import win32service
        import win32event
        import servicemanager

        class ObserveXAgentService(win32serviceutil.ServiceFramework):
            _svc_name_ = "ObserveXAgent"
            _svc_display_name_ = "ObserveX Monitoring Agent"
            _svc_description_ = "Collects system telemetry and streams it to the centralized ObserveX server."

            def __init__(self, args):
                win32serviceutil.ServiceFramework.__init__(self, args)
                self.stop_event = win32event.CreateEvent(None, 0, 0, None)
                self.running = True

            def SvcStop(self):
                self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
                self.running = False
                win32event.SetEvent(self.stop_event)

            def SvcDoRun(self):
                servicemanager.LogMsg(
                    servicemanager.EVENTLOG_INFORMATION_TYPE,
                    servicemanager.PYS_SERVICE_STARTED,
                    (self._svc_name_, ""),
                )
                self.main()

            def main(self):
                # Add project root to path so imports work
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if project_root not in sys.path:
                    sys.path.insert(0, project_root)

                from agent.agent import run_agent

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                async def run_with_stop():
                    task = asyncio.create_task(run_agent())
                    while self.running:
                        await asyncio.sleep(1)
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                try:
                    loop.run_until_complete(run_with_stop())
                except Exception as e:
                    servicemanager.LogErrorMsg(f"ObserveX Agent error: {e}")
                finally:
                    loop.close()

        def install_service():
            """Install the Windows service."""
            win32serviceutil.InstallService(
                ObserveXAgentService,
                ObserveXAgentService._svc_name_,
                ObserveXAgentService._svc_display_name_,
                startType=win32service.SERVICE_AUTO_START,
                description=ObserveXAgentService._svc_description_,
            )
            print(f"[Service] '{ObserveXAgentService._svc_display_name_}' installed successfully.")

        def start_service():
            """Start the Windows service."""
            win32serviceutil.StartService(ObserveXAgentService._svc_name_)
            print(f"[Service] '{ObserveXAgentService._svc_display_name_}' started.")

        def stop_service():
            """Stop the Windows service."""
            win32serviceutil.StopService(ObserveXAgentService._svc_name_)
            print(f"[Service] '{ObserveXAgentService._svc_display_name_}' stopped.")

        def remove_service():
            """Remove the Windows service."""
            win32serviceutil.RemoveService(ObserveXAgentService._svc_name_)
            print(f"[Service] '{ObserveXAgentService._svc_display_name_}' removed.")

        if __name__ == "__main__":
            if len(sys.argv) == 1:
                servicemanager.Initialize()
                servicemanager.PrepareToHostSingle(ObserveXAgentService)
                servicemanager.StartServiceCtrlDispatcher()
            else:
                win32serviceutil.HandleCommandLine(ObserveXAgentService)

    except ImportError:
        print("[Service] pywin32 is required for Windows service support.")
        print("[Service] Install it with: pip install pywin32")
else:
    # Non-Windows: provide a stub that explains this is Windows-only
    print("[Service] Windows service is only available on Windows.")
    print("[Service] On Linux/macOS, use systemd or launchd instead.")
