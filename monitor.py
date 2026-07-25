import os
import sys
import time
import datetime
import platform
import subprocess
import threading
import winreg
import win32com.client
import win32evtlog
import win32evtlogutil
import psutil

class SystemMonitor:
    def __init__(self):
        self.lock = threading.Lock()
        self.live_metrics = {}
        self.static_info = {}
        self.installed_software = []
        self.update_history = []
        self.pending_updates = []
        self.is_fetching_updates = False
        self.process_cache = []
        self.process_tick = 0
        self.unplugged_time = None
        self.prev_proc_io = {}
        
        # Historical rates variables
        self.prev_disk_read = 0
        self.prev_disk_write = 0
        self.prev_net_sent = 0
        self.prev_net_recv = 0
        self.prev_time = time.time()
        self.refresh_interval = 0.2
        
        # Initialize IO counters
        try:
            disk_io = psutil.disk_io_counters()
            if disk_io:
                self.prev_disk_read = disk_io.read_bytes
                self.prev_disk_write = disk_io.write_bytes
        except Exception:
            pass
            
        try:
            net_io = psutil.net_io_counters()
            if net_io:
                self.prev_net_sent = net_io.bytes_sent
                self.prev_net_recv = net_io.bytes_recv
        except Exception:
            pass

        # Establish CPU baseline so first tick returns real values instead of 0.0
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass

        # Load static hardware/OS details once
        self._load_static_info()
        
        # Load software list once
        self._load_installed_software()
        
        # Load updates list in a background thread to prevent startup block
        threading.Thread(target=self.refresh_windows_updates, daemon=True).start()
        
        # Start background loop to compute live speed rates and update metrics cache
        self.running = True
        self.monitor_thread = threading.Thread(target=self._live_monitor_loop, daemon=True)
        self.monitor_thread.start()

    def stop(self):
        self.running = False

    def _load_static_info(self):
        info = {}
        info["computer_name"] = platform.node()
        info["os_name"] = platform.system()
        info["os_release"] = platform.release()
        info["os_version"] = platform.version()
        info["cpu_model"] = platform.processor()
        info["cpu_cores_physical"] = psutil.cpu_count(logical=False)
        info["cpu_cores_logical"] = psutil.cpu_count(logical=True)
        info["total_ram_gb"] = round(psutil.virtual_memory().total / (1024**3), 2)
        
        # Motherboard & BIOS info (via WMI)
        info["motherboard_mfg"] = "N/A"
        info["motherboard_product"] = "N/A"
        info["bios_name"] = "N/A"
        info["bios_version"] = "N/A"
        info["gpu_model"] = "N/A"
        
        try:
            # CoInitialize is needed for WMI inside threads, but this runs in init
            import pythoncom
            pythoncom.CoInitialize()
            wmi = win32com.client.GetObject("winmgmts:")
            
            # Motherboard
            for board in wmi.InstancesOf("Win32_BaseBoard"):
                info["motherboard_mfg"] = getattr(board, "Manufacturer", "N/A")
                info["motherboard_product"] = getattr(board, "Product", "N/A")
                break
                
            # BIOS
            for bios in wmi.InstancesOf("Win32_BIOS"):
                info["bios_name"] = getattr(bios, "Name", "N/A")
                info["bios_version"] = getattr(bios, "Version", "N/A")
                break

            # GPU Names
            gpu_names = []
            for gpu in wmi.InstancesOf("Win32_VideoController"):
                if gpu.Name:
                    gpu_names.append(gpu.Name)
            if gpu_names:
                info["gpu_model"] = ", ".join(gpu_names)
        except Exception as e:
            print(f"Error reading WMI static data: {e}")
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
                
        # Storage devices
        storage = []
        try:
            for part in psutil.disk_partitions(all=False):
                if 'cdrom' in part.opts or not part.mountpoint:
                    continue
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    storage.append({
                        "device": part.device,
                        "mountpoint": part.mountpoint,
                        "fstype": part.fstype,
                        "total_gb": round(usage.total / (1024**3), 2),
                        "used_gb": round(usage.used / (1024**3), 2),
                        "free_gb": round(usage.free / (1024**3), 2),
                        "percent": usage.percent
                    })
                except Exception:
                    # Drive might not be ready (e.g. SD Card slots, DVD drives)
                    continue
        except Exception as e:
            print(f"Error reading disk partitions: {e}")
        info["storage_devices"] = storage
        
        # Network Adapters
        adapters = []
        try:
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            for name, addresses in addrs.items():
                ip = "No IP"
                mac = "No MAC"
                for addr in addresses:
                    if addr.family == 2:  # AF_INET
                        ip = addr.address
                    elif addr.family == -1:  # AF_LINK (MAC address in Windows)
                        mac = addr.address
                
                is_up = False
                speed = 0
                if name in stats:
                    is_up = stats[name].isup
                    speed = stats[name].speed  # in Mbps
                    
                adapters.append({
                    "name": name,
                    "ip": ip,
                    "mac": mac,
                    "status": "Up" if is_up else "Down",
                    "speed_mbps": speed
                })
        except Exception as e:
            print(f"Error reading network adapters: {e}")
        info["network_adapters"] = adapters

        self.static_info = info

    def _load_installed_software(self):
        targets = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", winreg.KEY_WOW64_64KEY),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", winreg.KEY_WOW64_32KEY),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0),
        ]
        
        apps = []
        seen = set()
        
        for hkey, path, access_flag in targets:
            try:
                access = winreg.KEY_READ | access_flag if access_flag else winreg.KEY_READ
                key = winreg.OpenKey(hkey, path, 0, access)
                num_subkeys = winreg.QueryInfoKey(key)[0]
                
                for i in range(num_subkeys):
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        subkey = winreg.OpenKey(key, subkey_name, 0, access)
                        
                        try:
                            name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                        except Exception:
                            continue
                        
                        if not name or name.strip() in seen:
                            continue
                            
                        version = "N/A"
                        publisher = "N/A"
                        install_date = "N/A"
                        try:
                            version, _ = winreg.QueryValueEx(subkey, "DisplayVersion")
                        except Exception:
                            pass
                        try:
                            publisher, _ = winreg.QueryValueEx(subkey, "Publisher")
                        except Exception:
                            pass
                        try:
                            install_date, _ = winreg.QueryValueEx(subkey, "InstallDate")
                            # Format YYYYMMDD to YYYY-MM-DD
                            if len(install_date) == 8 and install_date.isdigit():
                                install_date = f"{install_date[:4]}-{install_date[4:6]}-{install_date[6:]}"
                        except Exception:
                            pass
                            
                        seen.add(name.strip())
                        apps.append({
                            "name": name.strip(),
                            "version": version,
                            "publisher": publisher,
                            "install_date": install_date
                        })
                    except OSError:
                        continue
            except OSError:
                continue
        # Sort alphabetically
        self.installed_software = sorted(apps, key=lambda x: x["name"].lower())

    def refresh_windows_updates(self):
        if self.is_fetching_updates:
            return
            
        self.is_fetching_updates = True
        try:
            import pythoncom
            pythoncom.CoInitialize()
            
            session = win32com.client.Dispatch("Microsoft.Update.Session")
            searcher = session.CreateUpdateSearcher()
            
            # 1. Fetch History
            history_count = searcher.GetTotalHistoryCount()
            hist = []
            if history_count > 0:
                # Query last 100 entries max to keep it fast
                limit = min(history_count, 100)
                history = searcher.QueryHistory(history_count - limit, limit)
                
                result_map = {
                    0: "Not Started",
                    1: "In Progress",
                    2: "Succeeded",
                    3: "Succeeded (with errors)",
                    4: "Failed",
                    5: "Aborted"
                }
                
                for item in history:
                    date_str = "N/A"
                    try:
                        date_str = item.Date.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        pass
                    kb_ids = []
                    try:
                        if item.KBArticleIDs:
                            for idx in range(item.KBArticleIDs.Count):
                                kb_ids.append(item.KBArticleIDs.Item(idx))
                    except Exception:
                        pass
                    kb_article_str = ", ".join(kb_ids) if kb_ids else "N/A"

                    hist.append({
                        "title": item.Title,
                        "date": date_str,
                        "result": result_map.get(item.ResultCode, f"Unknown ({item.ResultCode})"),
                        "kb_article": kb_article_str
                    })
                # Reverse to show newest updates first
                hist.reverse()
            self.update_history = hist
            
            # 2. Fetch Pending
            pending = []
            # Search criteria: not installed and not hidden
            search_result = searcher.Search("IsInstalled=0 and IsHidden=0")
            for i in range(search_result.Updates.Count):
                update = search_result.Updates.Item(i)
                pending.append({
                    "title": update.Title,
                    "mandatory": update.IsMandatory,
                    "description": update.Description[:200] + "..." if update.Description else "No description"
                })
            self.pending_updates = pending
            
        except Exception as e:
            print(f"Error fetching Windows updates: {e}")
        finally:
            self.is_fetching_updates = False
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    def _query_nvidia_gpu(self):
        """Query nvidia-smi. Returns GPU usage %, total memory, used memory, temp, name, power."""
        try:
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,utilization.gpu,utilization.memory,temperature.gpu,memory.total,memory.used,power.draw", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, check=True, timeout=1.0
            )
            parts = [x.strip() for x in res.stdout.strip().split(",")]
            if len(parts) >= 7:
                try:
                    gpu_power = float(parts[6])
                    if gpu_power > 150.0:  # Clamp Optimus GPU sleep state bug (reports ~590W)
                        gpu_power = 0.0
                except Exception:
                    gpu_power = 0.0
                return {
                    "available": True,
                    "name": parts[0],
                    "usage_percent": float(parts[1]),
                    "memory_usage_percent": round((float(parts[5]) / float(parts[4])) * 100, 1),
                    "memory_total_mb": float(parts[4]),
                    "memory_used_mb": float(parts[5]),
                    "temperature": float(parts[3]),
                    "power_w": gpu_power
                }
        except Exception:
            pass
        return {"available": False}

    def _query_wmi_gpu_fallback(self):
        """Query WMI for static GPU data and active status if nvidia-smi is not available."""
        # WMI query inside threads needs COM init
        gpu_info = {"available": False, "name": "N/A", "usage_percent": 0.0, "memory_usage_percent": 0.0, "memory_total_mb": 0.0, "memory_used_mb": 0.0, "temperature": 0.0}
        try:
            import pythoncom
            pythoncom.CoInitialize()
            wmi = win32com.client.GetObject("winmgmts:")
            
            gpus = wmi.InstancesOf("Win32_VideoController")
            gpu_names = []
            for gpu in gpus:
                if gpu.Name:
                    gpu_names.append(gpu.Name)
                    # Attempt to extract adapter RAM
                    ram = getattr(gpu, "AdapterRAM", 0) or 0
                    if ram > 0 and gpu_info["memory_total_mb"] == 0:
                        gpu_info["memory_total_mb"] = round(ram / (1024**2), 1)
                        
            if gpu_names:
                gpu_info["name"] = ", ".join(gpu_names)
                gpu_info["available"] = True
                
                # Check for Intel/AMD GPU performance usage in registry/counters
                # As a fallback on non-Nvidia, we can estimate active GPU usage from Win32_PerfFormattedData_GPUPerformanceAnalyzers_GPUEngine
                try:
                    engines = wmi.InstancesOf("Win32_PerfFormattedData_GPUPerformanceAnalyzers_GPUEngine")
                    total_usage = 0.0
                    for eng in engines:
                        total_usage += float(getattr(eng, "UtilizationPercentage", 0) or 0)
                    gpu_info["usage_percent"] = min(total_usage, 100.0)
                except Exception:
                    gpu_info["usage_percent"] = 0.0
        except Exception:
            pass
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
        return gpu_info

    def _live_monitor_loop(self):
        # We run this loop in the background to calculate speeds correctly
        # and store metrics in self.live_metrics.
        import pythoncom
        pythoncom.CoInitialize()
        
        wmi_wmi = None
        wmi_cim = None
        
        # Local cache for slow-tick values to update them only once per second
        slow_metrics = {
            "cpu_temp": "N/A",
            "battery_percent": 100,
            "battery_plugged": True,
            "battery_time_left": "Charging...",
            "battery_time_used": "N/A",
            "disk_usage_percent": 0.0,
            "disk_total_gb": 0.0,
            "disk_used_gb": 0.0,
            "disk_free_gb": 0.0,
            "disk_read_speed": 0.0,
            "disk_write_speed": 0.0,
            "net_upload_speed": 0.0,
            "net_download_speed": 0.0,
            "net_bytes_sent": 0,
            "net_bytes_received": 0,
            "system_uptime": "0d 0h 0m 0s",
            "boot_time": "N/A",
            "network_connected": True
        }
        
        last_slow_tick = 0.0
        
        while self.running:
            try:
                # Re-connect WMI if None (self-healing cached connections)
                if wmi_wmi is None:
                    try:
                        wmi_wmi = win32com.client.GetObject("winmgmts:\\\\.\\root\\wmi")
                    except Exception:
                        pass
                if wmi_cim is None:
                    try:
                        wmi_cim = win32com.client.GetObject("winmgmts:")
                    except Exception:
                        pass

                # Fast telemetry: CPU and RAM loads (always updated)
                cpu_usage = psutil.cpu_percent(interval=None)
                cpu_freq_info = psutil.cpu_freq()
                cpu_freq = f"{round(cpu_freq_info.current / 1000, 2)} GHz" if cpu_freq_info else "N/A"
                
                ram = psutil.virtual_memory()
                ram_total = round(ram.total / (1024**3), 2)
                ram_used = round(ram.used / (1024**3), 2)
                ram_avail = round(ram.available / (1024**3), 2)
                ram_percent = ram.percent

                # Fast telemetry: GPU load & power
                gpu = self._query_nvidia_gpu()
                if not gpu["available"]:
                    gpu = self._query_wmi_gpu_fallback()
                gpu_power_w = gpu.get("power_w", 0.0) if gpu.get("available") else 0.0

                # Fast telemetry: Total and CPU power counters (from WMI performance classes)
                power_total_w = 0.0
                power_cpu_w = 0.0
                if wmi_cim:
                    try:
                        for meter in wmi_cim.ExecQuery("SELECT Power FROM Win32_PerfFormattedData_PowerMeterCounter_PowerMeter"):
                            power_total_w = float(getattr(meter, "Power", 0) or 0) / 1000.0
                            break
                    except Exception:
                        pass
                        
                    try:
                        for energy in wmi_cim.ExecQuery("SELECT Name, Power FROM Win32_PerfFormattedData_PowerMeterCounter_EnergyMeter"):
                            name = getattr(energy, "Name", "")
                            if "PKG" in name or "Package" in name:
                                power_cpu_w = float(getattr(energy, "Power", 0) or 0) / 1000.0
                                break
                    except Exception:
                        pass

                # Slow telemetry: run once every 1.0 second (independent of refresh interval)
                now_time = time.time()
                if now_time - last_slow_tick >= 1.0:
                    last_slow_tick = now_time
                    
                    # 1. Non-admin CPU temperature
                    cpu_temp = "N/A"
                    if wmi_cim:
                        try:
                            max_temp_c = -273.15
                            for zone in wmi_cim.ExecQuery("SELECT HighPrecisionTemperature FROM Win32_PerfFormattedData_Counters_ThermalZoneInformation"):
                                raw = getattr(zone, "HighPrecisionTemperature", 0)
                                if raw > 0:
                                    celsius = (raw - 2732) / 10.0
                                    if celsius > max_temp_c:
                                        max_temp_c = celsius
                            if max_temp_c > -100.0:
                                cpu_temp = f"{max_temp_c:.1f} °C"
                        except Exception:
                            pass
                    
                    # 2. Admin fallback CPU temp
                    if cpu_temp == "N/A" and wmi_wmi:
                        try:
                            for zone in wmi_wmi.ExecQuery("SELECT CurrentTemperature FROM MSAcpi_ThermalZoneTemperature"):
                                raw = zone.CurrentTemperature
                                celsius = (raw - 2732) / 10.0
                                cpu_temp = f"{celsius:.1f} °C"
                                break
                        except Exception:
                            cpu_temp = "N/A (Admin Required)"
                    slow_metrics["cpu_temp"] = cpu_temp

                    # 3. Battery status and charge/discharge rate
                    charge_rate_mw = 0
                    discharge_rate_mw = 0
                    if wmi_wmi:
                        try:
                            for status in wmi_wmi.ExecQuery("SELECT ChargeRate, DischargeRate FROM BatteryStatus"):
                                charge_rate_mw = getattr(status, "ChargeRate", 0) or 0
                                discharge_rate_mw = getattr(status, "DischargeRate", 0) or 0
                                break
                        except Exception:
                            wmi_wmi = None

                    batt = psutil.sensors_battery()
                    if batt:
                        batt_percent = batt.percent
                        batt_plugged = batt.power_plugged
                        batt_secsleft = batt.secsleft
                    else:
                        batt_percent = 100
                        batt_plugged = True
                        batt_secsleft = -1
                        
                    if batt_plugged:
                        batt_time_left = "Fully Charged" if batt_percent >= 99 else "Charging..."
                    else:
                        if batt_secsleft == psutil.POWER_TIME_UNKNOWN or batt_secsleft == 4294967295 or batt_secsleft < 0:
                            batt_time_left = "Calculating..."
                        elif batt_secsleft == psutil.POWER_TIME_UNLIMITED:
                            batt_time_left = "Unlimited"
                        else:
                            shours, sremainder = divmod(batt_secsleft, 3600)
                            sminutes, sseconds = divmod(sremainder, 60)
                            batt_time_left = f"{shours}h {sminutes}m"
                            
                    if not batt_plugged:
                        if self.unplugged_time is None:
                            self.unplugged_time = time.time()
                        elapsed = time.time() - self.unplugged_time
                        uhours, uremainder = divmod(int(elapsed), 3600)
                        uminutes, useconds = divmod(uremainder, 60)
                        batt_time_used = f"{uhours}h {uminutes}m {useconds}s"
                    else:
                        self.unplugged_time = None
                        batt_time_used = "N/A (Plugged In)"

                    slow_metrics["battery_percent"] = batt_percent
                    slow_metrics["battery_plugged"] = batt_plugged
                    slow_metrics["battery_time_left"] = batt_time_left
                    slow_metrics["battery_time_used"] = batt_time_used
                    slow_metrics["charge_rate_mw"] = charge_rate_mw
                    slow_metrics["discharge_rate_mw"] = discharge_rate_mw

                    # 4. Storage partition usage
                    primary_mount = "C:\\" if os.name == 'nt' else '/'
                    disk = psutil.disk_usage(primary_mount)
                    slow_metrics["disk_total_gb"] = round(disk.total / (1024**3), 2)
                    slow_metrics["disk_used_gb"] = round(disk.used / (1024**3), 2)
                    slow_metrics["disk_free_gb"] = round(disk.free / (1024**3), 2)
                    slow_metrics["disk_usage_percent"] = disk.percent

                    # 5. Speed rates (Disk and Network I/O)
                    dt = now_time - self.prev_time
                    if dt <= 0:
                        dt = 1.0
                    self.prev_time = now_time

                    disk_read_speed = 0.0
                    disk_write_speed = 0.0
                    try:
                        disk_io = psutil.disk_io_counters()
                        if disk_io:
                            disk_read_speed = (disk_io.read_bytes - self.prev_disk_read) / dt
                            disk_write_speed = (disk_io.write_bytes - self.prev_disk_write) / dt
                            self.prev_disk_read = disk_io.read_bytes
                            self.prev_disk_write = disk_io.write_bytes
                    except Exception:
                        pass
                    slow_metrics["disk_read_speed"] = disk_read_speed
                    slow_metrics["disk_write_speed"] = disk_write_speed

                    net_upload_speed = 0.0
                    net_download_speed = 0.0
                    net_total_sent = 0
                    net_total_recv = 0
                    try:
                        net_io = psutil.net_io_counters()
                        if net_io:
                            net_upload_speed = (net_io.bytes_sent - self.prev_net_sent) / dt
                            net_download_speed = (net_io.bytes_recv - self.prev_net_recv) / dt
                            net_total_sent = net_io.bytes_sent
                            net_total_recv = net_io.bytes_recv
                            self.prev_net_sent = net_io.bytes_sent
                            self.prev_net_recv = net_io.bytes_recv
                    except Exception:
                        pass
                    slow_metrics["net_upload_speed"] = net_upload_speed
                    slow_metrics["net_download_speed"] = net_download_speed
                    slow_metrics["net_bytes_sent"] = net_total_sent
                    slow_metrics["net_bytes_received"] = net_total_recv

                    # 6. Uptime and system clock
                    boot_time_ts = psutil.boot_time()
                    boot_time = datetime.datetime.fromtimestamp(boot_time_ts).strftime("%Y-%m-%d %H:%M:%S")
                    uptime_sec = max(0, int(time.time() - boot_time_ts))
                    days, remainder = divmod(uptime_sec, 86400)
                    hours, remainder = divmod(remainder, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    slow_metrics["system_uptime"] = f"{days}d {hours}h {minutes}m {seconds}s"
                    slow_metrics["boot_time"] = boot_time

                    # 7. Check network connectivity
                    has_active_net = False
                    for adapter in self.static_info.get("network_adapters", []):
                        if adapter["status"] == "Up" and adapter["ip"] != "No IP" and adapter["ip"] != "127.0.0.1":
                            has_active_net = True
                            break
                    slow_metrics["network_connected"] = has_active_net

                # Dynamic charger inputs from slow ticks
                power_charging_w = 0.0
                if slow_metrics["battery_plugged"]:
                    battery_charge_w = float(slow_metrics.get("charge_rate_mw", 0)) / 1000.0
                    # If charge rate readout is buggy (returns 0W or very low while battery is low/charging), estimate it:
                    if battery_charge_w < 5.0 and slow_metrics["battery_percent"] < 95:
                        # Dynamic estimation based on standard battery charging curve
                        battery_charge_w = round(32.0 * (1.0 - slow_metrics["battery_percent"] / 100.0), 2)
                        if battery_charge_w < 10.0:
                            battery_charge_w = 12.0
                    
                    # Total system load consumption
                    system_consumption = power_cpu_w + gpu_power_w + 12.0
                    if power_total_w < system_consumption:
                        power_total_w = system_consumption
                    
                    # Charger supplies system load + power going into charging the battery cell
                    power_charging_w = round(power_total_w + battery_charge_w, 2)
                    # Total power drawn by the laptop from the wall adapter is charger input
                    power_total_w = power_charging_w
                else:
                    if power_total_w == 0.0 and slow_metrics.get("discharge_rate_mw", 0) > 0:
                        power_total_w = float(slow_metrics["discharge_rate_mw"]) / 1000.0

                # 8. Calculate System Health Score
                health_score = 100
                if cpu_usage > 90:
                    health_score -= 15
                elif cpu_usage > 80:
                    health_score -= 8
                    
                if ram_percent > 90:
                    health_score -= 20
                elif ram_percent > 80:
                    health_score -= 10
                    
                if slow_metrics["disk_usage_percent"] > 95:
                    health_score -= 15
                elif slow_metrics["disk_usage_percent"] > 90:
                    health_score -= 8
                    
                if gpu.get("temperature", 0) > 85:
                    health_score -= 10
                elif gpu.get("temperature", 0) > 75:
                    health_score -= 4
                    
                if not slow_metrics["network_connected"]:
                    health_score -= 25
                health_score = max(0, min(100, health_score))
                
                # Update live metrics dictionary thread-safely
                with self.lock:
                    self.live_metrics = {
                        "cpu_usage": cpu_usage,
                        "cpu_frequency": cpu_freq,
                        "cpu_temp": slow_metrics["cpu_temp"],
                        "gpu_name": gpu["name"],
                        "gpu_usage": gpu["usage_percent"],
                        "gpu_memory_usage": gpu["memory_usage_percent"],
                        "gpu_memory_total": gpu["memory_total_mb"],
                        "gpu_memory_used": gpu["memory_used_mb"],
                        "gpu_temp": f"{gpu['temperature']} °C" if gpu.get("temperature") else "N/A",
                        "ram_total_gb": ram_total,
                        "ram_used_gb": ram_used,
                        "ram_avail_gb": ram_avail,
                        "ram_usage_percent": ram_percent,
                        "disk_usage_percent": slow_metrics["disk_usage_percent"],
                        "disk_total_gb": slow_metrics["disk_total_gb"],
                        "disk_used_gb": slow_metrics["disk_used_gb"],
                        "disk_free_gb": slow_metrics["disk_free_gb"],
                        "disk_read_speed": slow_metrics["disk_read_speed"],
                        "disk_write_speed": slow_metrics["disk_write_speed"],
                        "net_upload_speed": slow_metrics["net_upload_speed"],
                        "net_download_speed": slow_metrics["net_download_speed"],
                        "net_bytes_sent": slow_metrics["net_bytes_sent"],
                        "net_bytes_received": slow_metrics["net_bytes_received"],
                        "system_uptime": slow_metrics["system_uptime"],
                        "boot_time": slow_metrics["boot_time"],
                        "current_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "health_score": health_score,
                        "network_connected": slow_metrics["network_connected"],
                        "battery_percent": slow_metrics["battery_percent"],
                        "battery_plugged": slow_metrics["battery_plugged"],
                        "battery_time_left": slow_metrics["battery_time_left"],
                        "battery_time_used": slow_metrics["battery_time_used"],
                        "power_total_w": round(power_total_w, 2),
                        "power_cpu_w": round(power_cpu_w, 2),
                        "power_gpu_w": round(gpu_power_w, 2),
                        "power_charging_w": round(power_charging_w, 2)
                    }
                # Update process cache every 3 seconds
                self.process_tick += 1
                if self.process_tick >= 15 or not self.process_cache: # Scaled for fast tick rate (15 * 0.2s = 3.0s)
                    self.process_tick = 0
                    threading.Thread(target=self._update_process_cache, daemon=True).start()
            except Exception as e:
                print(f"Error in monitor loop: {e}")
                
            time.sleep(self.refresh_interval)

    def get_live_metrics(self):
        with self.lock:
            return self.live_metrics.copy()

    def _update_process_cache(self):
        processes = []
        curr_time = time.time()
        
        # We need to know system download/upload rates to distribute them
        # Let's get system speeds from self.live_metrics
        with self.lock:
            sys_up = self.live_metrics.get("net_upload_speed", 0.0)
            sys_down = self.live_metrics.get("net_download_speed", 0.0)
            
        # Get active PIDs and stats
        raw_procs = []
        total_connections = 0
        
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info', 'num_threads', 'status', 'exe', 'io_counters']):
            try:
                pinfo = proc.info
                pid = pinfo["pid"]
                
                # Retrieve connection count (avoiding deprecation warnings & exceptions)
                try:
                    # Using net_connections() as connections() is deprecated in newer psutil
                    conns = len(proc.net_connections())
                except Exception:
                    conns = 0
                
                total_connections += conns
                
                raw_procs.append({
                    "pid": pid,
                    "name": pinfo["name"] or "Unknown",
                    "cpu_usage": round(pinfo["cpu_percent"] or 0, 1),
                    "memory_info": pinfo["memory_info"],
                    "threads": pinfo["num_threads"] or 1,
                    "status": pinfo["status"] or "unknown",
                    "path": pinfo["exe"] or "N/A",
                    "io_counters": pinfo["io_counters"],
                    "connections": conns
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
                
        # Calculate I/O speeds
        new_prev_io = {}
        for p in raw_procs:
            pid = p["pid"]
            io = p["io_counters"]
            
            read_speed = 0.0
            write_speed = 0.0
            
            if io:
                read_bytes = io.read_bytes
                write_bytes = io.write_bytes
                
                if pid in self.prev_proc_io:
                    prev_t, prev_r, prev_w = self.prev_proc_io[pid]
                    dt = curr_time - prev_t
                    if dt > 0:
                        read_speed = max(0.0, (read_bytes - prev_r) / dt)
                        write_speed = max(0.0, (write_bytes - prev_w) / dt)
                
                new_prev_io[pid] = (curr_time, read_bytes, write_bytes)
            
            # Distribute network speed based on connections fraction
            net_up_speed = 0.0
            net_down_speed = 0.0
            if total_connections > 0 and p["connections"] > 0:
                fraction = p["connections"] / total_connections
                net_up_speed = sys_up * fraction
                net_down_speed = sys_down * fraction
                
            mem_bytes = p["memory_info"].rss if p["memory_info"] else 0
            mem_mb = round(mem_bytes / (1024**2), 2)
            
            vms_bytes = p["memory_info"].vms if p["memory_info"] else 0
            commit_mb = round(vms_bytes / (1024**2), 2)
            
            processes.append({
                "pid": pid,
                "name": p["name"],
                "cpu_usage": p["cpu_usage"],
                "memory_mb": mem_mb, # working set / rss
                "commit_mb": commit_mb, # commit bytes
                "threads": p["threads"],
                "status": p["status"],
                "path": p["path"],
                "read_speed": round(read_speed, 1),
                "write_speed": round(write_speed, 1),
                "net_up_speed": round(net_up_speed, 1),
                "net_down_speed": round(net_down_speed, 1),
                "connections": p["connections"]
            })
            
        self.prev_proc_io = new_prev_io
        with self.lock:
            self.process_cache = processes

    def get_process_list(self):
        with self.lock:
            return self.process_cache.copy()

    def get_event_logs(self, limit=1000):
        server = 'localhost'
        log_types = ['System', 'Application']
        severity_map = {
            1: "Error",
            2: "Warning",
            4: "Information",
            8: "Audit Success",
            16: "Audit Failure"
        }
        
        events_list = []
        for logtype in log_types:
            try:
                hand = win32evtlog.OpenEventLog(server, logtype)
                flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
                
                count = 0
                while count < (limit // len(log_types)):
                    events = win32evtlog.ReadEventLog(hand, flags, 0)
                    if not events:
                        break
                    for ev in events:
                        if count >= (limit // len(log_types)):
                            break
                        count += 1
                        
                        time_gen = "N/A"
                        try:
                            time_gen = ev.TimeGenerated.strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            pass
                            
                        # Handle message formatting safely
                        try:
                            msg = win32evtlogutil.SafeFormatMessage(ev, logtype)
                            msg = " ".join(msg.split()) if msg else "No description"
                        except Exception:
                            msg = f"Event ID {ev.EventID & 0xFFFF} from {ev.SourceName}."
                            
                        events_list.append({
                            "log_type": logtype,
                            "timestamp": time_gen,
                            "source": ev.SourceName or "Unknown",
                            "event_id": ev.EventID & 0xFFFF,
                            "severity": severity_map.get(ev.EventType, f"Unknown ({ev.EventType})"),
                            "message": msg
                        })
            except Exception as e:
                print(f"Error reading event log {logtype}: {e}")
                
        # Sort combined events by timestamp descending
        events_list.sort(key=lambda x: x["timestamp"], reverse=True)
        return events_list[:limit]

if __name__ == "__main__":
    import time
    print("Testing SystemMonitor data collection...")
    monitor = SystemMonitor()
    time.sleep(1.5)  # Wait for a couple of readings to calculate rates
    print("Live Metrics:")
    metrics = monitor.get_live_metrics()
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    
    print("\nStatic Info:")
    for k, v in monitor.static_info.items():
        if k != "storage_devices" and k != "network_adapters":
            print(f"  {k}: {v}")
            
    print(f"\nStorage Devices: {len(monitor.static_info['storage_devices'])}")
    print(f"Network Adapters: {len(monitor.static_info['network_adapters'])}")
    print(f"Installed Apps: {len(monitor.installed_software)}")
    print(f"Update History Cache: {len(monitor.update_history)}")
    print(f"Processes Sample: {len(monitor.get_process_list())}")
    print(f"Event Log Sample: {len(monitor.get_event_logs(10))}")
    monitor.stop()
