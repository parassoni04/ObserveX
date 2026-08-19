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
from contextlib import contextmanager


def _gb(b):
    return round(b / (1024**3), 2)


def _mb(b):
    return round(b / (1024**2), 2)


@contextmanager
def _com_init():
    import pythoncom
    pythoncom.CoInitialize()
    try:
        yield
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


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
        self.prev_disk_read = 0
        self.prev_disk_write = 0
        self.prev_net_sent = 0
        self.prev_net_recv = 0
        self.prev_time = time.time()
        self.refresh_interval = 0.2
        self.running = True

        # Initialize IO counters
        try:
            dio = psutil.disk_io_counters()
            if dio:
                self.prev_disk_read, self.prev_disk_write = dio.read_bytes, dio.write_bytes
        except Exception:
            pass
        try:
            nio = psutil.net_io_counters()
            if nio:
                self.prev_net_sent, self.prev_net_recv = nio.bytes_sent, nio.bytes_recv
        except Exception:
            pass

        # CPU baseline so first tick returns real values
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass

        self._load_static_info()
        self._load_installed_software()
        threading.Thread(target=self.refresh_windows_updates, daemon=True).start()

        self.monitor_thread = threading.Thread(target=self._live_monitor_loop, daemon=True)
        self.monitor_thread.start()

    def stop(self):
        self.running = False

    def _load_static_info(self):
        info = {
            "computer_name": platform.node(),
            "os_name": platform.system(),
            "os_release": platform.release(),
            "os_version": platform.version(),
            "cpu_model": platform.processor(),
            "cpu_cores_physical": psutil.cpu_count(logical=False),
            "cpu_cores_logical": psutil.cpu_count(logical=True),
            "total_ram_gb": _gb(psutil.virtual_memory().total),
            "motherboard_mfg": "N/A", "motherboard_product": "N/A",
            "bios_name": "N/A", "bios_version": "N/A", "gpu_model": "N/A",
        }

        try:
            with _com_init():
                wmi = win32com.client.GetObject("winmgmts:")
                for board in wmi.InstancesOf("Win32_BaseBoard"):
                    info["motherboard_mfg"] = getattr(board, "Manufacturer", "N/A")
                    info["motherboard_product"] = getattr(board, "Product", "N/A")
                    break
                for bios in wmi.InstancesOf("Win32_BIOS"):
                    info["bios_name"] = getattr(bios, "Name", "N/A")
                    info["bios_version"] = getattr(bios, "Version", "N/A")
                    break
                gpu_names = [gpu.Name for gpu in wmi.InstancesOf("Win32_VideoController") if gpu.Name]
                if gpu_names:
                    info["gpu_model"] = ", ".join(gpu_names)
        except Exception as e:
            print(f"Error reading WMI static data: {e}")

        # Storage devices
        storage = []
        try:
            for part in psutil.disk_partitions(all=False):
                if 'cdrom' in part.opts or not part.mountpoint:
                    continue
                try:
                    u = psutil.disk_usage(part.mountpoint)
                    storage.append({
                        "device": part.device, "mountpoint": part.mountpoint, "fstype": part.fstype,
                        "total_gb": _gb(u.total), "used_gb": _gb(u.used), "free_gb": _gb(u.free), "percent": u.percent,
                    })
                except Exception:
                    continue
        except Exception as e:
            print(f"Error reading disk partitions: {e}")
        info["storage_devices"] = storage

        # Network Adapters
        adapters = []
        try:
            addrs, stats = psutil.net_if_addrs(), psutil.net_if_stats()
            for name, addresses in addrs.items():
                ip, mac = "No IP", "No MAC"
                for addr in addresses:
                    if addr.family == 2:
                        ip = addr.address
                    elif addr.family == -1:
                        mac = addr.address
                st = stats.get(name)
                adapters.append({
                    "name": name, "ip": ip, "mac": mac,
                    "status": "Up" if st and st.isup else "Down",
                    "speed_mbps": st.speed if st else 0,
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
        apps, seen = [], set()
        for hkey, path, access_flag in targets:
            try:
                access = winreg.KEY_READ | access_flag if access_flag else winreg.KEY_READ
                key = winreg.OpenKey(hkey, path, 0, access)
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        subkey = winreg.OpenKey(key, winreg.EnumKey(key, i), 0, access)
                        try:
                            name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                        except Exception:
                            continue
                        if not name or name.strip() in seen:
                            continue
                        def _reg(sk, val):
                            try:
                                v, _ = winreg.QueryValueEx(sk, val)
                                return v
                            except Exception:
                                return "N/A"
                        version, publisher, install_date = _reg(subkey, "DisplayVersion"), _reg(subkey, "Publisher"), _reg(subkey, "InstallDate")
                        if isinstance(install_date, str) and len(install_date) == 8 and install_date.isdigit():
                            install_date = f"{install_date[:4]}-{install_date[4:6]}-{install_date[6:]}"
                        seen.add(name.strip())
                        apps.append({"name": name.strip(), "version": version, "publisher": publisher, "install_date": install_date})
                    except OSError:
                        continue
            except OSError:
                continue
        self.installed_software = sorted(apps, key=lambda x: x["name"].lower())

    def refresh_windows_updates(self):
        if self.is_fetching_updates:
            return
        self.is_fetching_updates = True
        try:
            with _com_init():
                session = win32com.client.Dispatch("Microsoft.Update.Session")
                searcher = session.CreateUpdateSearcher()

                # History
                hcount = searcher.GetTotalHistoryCount()
                hist = []
                if hcount > 0:
                    limit = min(hcount, 100)
                    history = searcher.QueryHistory(hcount - limit, limit)
                    result_map = {0: "Not Started", 1: "In Progress", 2: "Succeeded", 3: "Succeeded (with errors)", 4: "Failed", 5: "Aborted"}
                    for item in history:
                        date_str = "N/A"
                        try:
                            date_str = item.Date.strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            pass
                        kb_ids = []
                        try:
                            if item.KBArticleIDs:
                                kb_ids = [item.KBArticleIDs.Item(idx) for idx in range(item.KBArticleIDs.Count)]
                        except Exception:
                            pass
                        hist.append({
                            "title": item.Title, "date": date_str,
                            "result": result_map.get(item.ResultCode, f"Unknown ({item.ResultCode})"),
                            "kb_article": ", ".join(kb_ids) if kb_ids else "N/A",
                        })
                    hist.reverse()
                self.update_history = hist

                # Pending
                sr = searcher.Search("IsInstalled=0 and IsHidden=0")
                self.pending_updates = [
                    {"title": sr.Updates.Item(i).Title, "mandatory": sr.Updates.Item(i).IsMandatory,
                     "description": (sr.Updates.Item(i).Description[:200] + "...") if sr.Updates.Item(i).Description else "No description"}
                    for i in range(sr.Updates.Count)
                ]
        except Exception as e:
            print(f"Error fetching Windows updates: {e}")
        finally:
            self.is_fetching_updates = False

    def _get_gpu_info(self):
        """Try nvidia-smi first, then WMI fallback. Returns GPU dict."""
        # nvidia-smi path
        try:
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,utilization.gpu,utilization.memory,temperature.gpu,memory.total,memory.used,power.draw",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, check=True, timeout=1.0,
            )
            parts = [x.strip() for x in res.stdout.strip().split(",")]
            if len(parts) >= 7:
                gpu_power = float(parts[6])
                if gpu_power > 150.0:  # Clamp Optimus sleep state bug
                    gpu_power = 0.0
                return {
                    "available": True, "name": parts[0],
                    "usage_percent": float(parts[1]),
                    "memory_usage_percent": round((float(parts[5]) / float(parts[4])) * 100, 1),
                    "memory_total_mb": float(parts[4]), "memory_used_mb": float(parts[5]),
                    "temperature": float(parts[3]), "power_w": gpu_power,
                }
        except Exception:
            pass

        # WMI fallback
        gpu_info = {"available": False, "name": "N/A", "usage_percent": 0.0, "memory_usage_percent": 0.0,
                    "memory_total_mb": 0.0, "memory_used_mb": 0.0, "temperature": 0.0}
        try:
            with _com_init():
                wmi = win32com.client.GetObject("winmgmts:")
                gpu_names = []
                for gpu in wmi.InstancesOf("Win32_VideoController"):
                    if gpu.Name:
                        gpu_names.append(gpu.Name)
                        ram = getattr(gpu, "AdapterRAM", 0) or 0
                        if ram > 0 and gpu_info["memory_total_mb"] == 0:
                            gpu_info["memory_total_mb"] = round(ram / (1024**2), 1)
                if gpu_names:
                    gpu_info["name"] = ", ".join(gpu_names)
                    gpu_info["available"] = True
                    try:
                        engines = wmi.InstancesOf("Win32_PerfFormattedData_GPUPerformanceAnalyzers_GPUEngine")
                        total = sum(float(getattr(e, "UtilizationPercentage", 0) or 0) for e in engines)
                        gpu_info["usage_percent"] = min(total, 100.0)
                    except Exception:
                        pass
        except Exception:
            pass
        return gpu_info

    def _live_monitor_loop(self):
        import pythoncom
        pythoncom.CoInitialize()

        wmi_wmi, wmi_cim = None, None
        # Slow-tick cache (updates every 1s regardless of refresh_interval)
        slow = {
            "cpu_temp": "N/A", "battery_percent": 100, "battery_plugged": True,
            "battery_time_left": "Charging...", "battery_time_used": "N/A",
            "disk_usage_percent": 0.0, "disk_total_gb": 0.0, "disk_used_gb": 0.0, "disk_free_gb": 0.0,
            "disk_read_speed": 0.0, "disk_write_speed": 0.0,
            "net_upload_speed": 0.0, "net_download_speed": 0.0,
            "net_bytes_sent": 0, "net_bytes_received": 0,
            "system_uptime": "0d 0h 0m 0s", "boot_time": "N/A", "network_connected": True,
            "charge_rate_mw": 0, "discharge_rate_mw": 0,
        }
        last_slow_tick = 0.0

        while self.running:
            try:
                # Reconnect WMI if needed (self-healing)
                if wmi_wmi is None:
                    try:
                        wmi_wmi = win32com.client.GetObject(r"winmgmts:\\.\root\wmi")
                    except Exception:
                        pass
                if wmi_cim is None:
                    try:
                        wmi_cim = win32com.client.GetObject("winmgmts:")
                    except Exception:
                        pass

                # Fast telemetry: CPU, RAM, GPU
                cpu_usage = psutil.cpu_percent(interval=None)
                cpu_freq_info = psutil.cpu_freq()
                cpu_freq = f"{round(cpu_freq_info.current / 1000, 2)} GHz" if cpu_freq_info else "N/A"
                ram = psutil.virtual_memory()
                gpu = self._get_gpu_info()
                gpu_power_w = gpu.get("power_w", 0.0) if gpu.get("available") else 0.0

                # Fast telemetry: Power counters
                power_total_w, power_cpu_w = 0.0, 0.0
                if wmi_cim:
                    try:
                        for m in wmi_cim.ExecQuery("SELECT Power FROM Win32_PerfFormattedData_PowerMeterCounter_PowerMeter"):
                            power_total_w = float(getattr(m, "Power", 0) or 0) / 1000.0
                            break
                    except Exception:
                        pass
                    try:
                        for e in wmi_cim.ExecQuery("SELECT Name, Power FROM Win32_PerfFormattedData_PowerMeterCounter_EnergyMeter"):
                            if "PKG" in (getattr(e, "Name", "") or "") or "Package" in (getattr(e, "Name", "") or ""):
                                power_cpu_w = float(getattr(e, "Power", 0) or 0) / 1000.0
                                break
                    except Exception:
                        pass

                # Slow telemetry: once per second
                now = time.time()
                if now - last_slow_tick >= 1.0:
                    last_slow_tick = now

                    # CPU temperature
                    cpu_temp = "N/A"
                    if wmi_cim:
                        try:
                            max_t = -273.15
                            for z in wmi_cim.ExecQuery("SELECT HighPrecisionTemperature FROM Win32_PerfFormattedData_Counters_ThermalZoneInformation"):
                                raw = getattr(z, "HighPrecisionTemperature", 0)
                                if raw > 0:
                                    c = (raw - 2732) / 10.0
                                    if c > max_t:
                                        max_t = c
                            if max_t > -100.0:
                                cpu_temp = f"{max_t:.1f} °C"
                        except Exception:
                            pass
                    if cpu_temp == "N/A" and wmi_wmi:
                        try:
                            for z in wmi_wmi.ExecQuery("SELECT CurrentTemperature FROM MSAcpi_ThermalZoneTemperature"):
                                cpu_temp = f"{(z.CurrentTemperature - 2732) / 10.0:.1f} °C"
                                break
                        except Exception:
                            cpu_temp = "N/A (Admin Required)"
                    slow["cpu_temp"] = cpu_temp

                    # Battery
                    charge_rate_mw, discharge_rate_mw = 0, 0
                    if wmi_wmi:
                        try:
                            for st in wmi_wmi.ExecQuery("SELECT ChargeRate, DischargeRate FROM BatteryStatus"):
                                charge_rate_mw = getattr(st, "ChargeRate", 0) or 0
                                discharge_rate_mw = getattr(st, "DischargeRate", 0) or 0
                                break
                        except Exception:
                            wmi_wmi = None

                    batt = psutil.sensors_battery()
                    batt_pct = batt.percent if batt else 100
                    batt_plug = batt.power_plugged if batt else True
                    batt_secs = batt.secsleft if batt else -1

                    if batt_plug:
                        batt_time_left = "Fully Charged" if batt_pct >= 99 else "Charging..."
                    elif batt_secs == psutil.POWER_TIME_UNKNOWN or batt_secs == 4294967295 or batt_secs < 0:
                        batt_time_left = "Calculating..."
                    elif batt_secs == psutil.POWER_TIME_UNLIMITED:
                        batt_time_left = "Unlimited"
                    else:
                        h, r = divmod(batt_secs, 3600)
                        batt_time_left = f"{h}h {r // 60}m"

                    if not batt_plug:
                        if self.unplugged_time is None:
                            self.unplugged_time = time.time()
                        el = int(time.time() - self.unplugged_time)
                        uh, ur = divmod(el, 3600)
                        um, us = divmod(ur, 60)
                        batt_time_used = f"{uh}h {um}m {us}s"
                    else:
                        self.unplugged_time = None
                        batt_time_used = "N/A (Plugged In)"

                    slow.update({
                        "battery_percent": batt_pct, "battery_plugged": batt_plug,
                        "battery_time_left": batt_time_left, "battery_time_used": batt_time_used,
                        "charge_rate_mw": charge_rate_mw, "discharge_rate_mw": discharge_rate_mw,
                    })

                    # Storage
                    primary = "C:\\" if os.name == 'nt' else '/'
                    disk = psutil.disk_usage(primary)
                    slow.update({
                        "disk_total_gb": _gb(disk.total), "disk_used_gb": _gb(disk.used),
                        "disk_free_gb": _gb(disk.free), "disk_usage_percent": disk.percent,
                    })

                    # I/O speeds
                    dt = max(now - self.prev_time, 0.001)
                    self.prev_time = now
                    try:
                        dio = psutil.disk_io_counters()
                        if dio:
                            slow["disk_read_speed"] = (dio.read_bytes - self.prev_disk_read) / dt
                            slow["disk_write_speed"] = (dio.write_bytes - self.prev_disk_write) / dt
                            self.prev_disk_read, self.prev_disk_write = dio.read_bytes, dio.write_bytes
                    except Exception:
                        pass
                    try:
                        nio = psutil.net_io_counters()
                        if nio:
                            slow["net_upload_speed"] = (nio.bytes_sent - self.prev_net_sent) / dt
                            slow["net_download_speed"] = (nio.bytes_recv - self.prev_net_recv) / dt
                            slow["net_bytes_sent"], slow["net_bytes_received"] = nio.bytes_sent, nio.bytes_recv
                            self.prev_net_sent, self.prev_net_recv = nio.bytes_sent, nio.bytes_recv
                    except Exception:
                        pass

                    # Uptime
                    bt = psutil.boot_time()
                    uptime = max(0, int(time.time() - bt))
                    d, r = divmod(uptime, 86400)
                    h, r = divmod(r, 3600)
                    m, s = divmod(r, 60)
                    slow["system_uptime"] = f"{d}d {h}h {m}m {s}s"
                    slow["boot_time"] = datetime.datetime.fromtimestamp(bt).strftime("%Y-%m-%d %H:%M:%S")

                    # Network connectivity
                    slow["network_connected"] = any(
                        a["status"] == "Up" and a["ip"] not in ("No IP", "127.0.0.1")
                        for a in self.static_info.get("network_adapters", [])
                    )

                # Power calculations
                power_charging_w = 0.0
                if slow["battery_plugged"]:
                    battery_charge_w = float(slow.get("charge_rate_mw", 0)) / 1000.0
                    if battery_charge_w < 5.0 and slow["battery_percent"] < 95:
                        battery_charge_w = max(round(32.0 * (1.0 - slow["battery_percent"] / 100.0), 2), 12.0)
                    system_consumption = power_cpu_w + gpu_power_w + 12.0
                    if power_total_w < system_consumption:
                        power_total_w = system_consumption
                    power_charging_w = round(power_total_w + battery_charge_w, 2)
                    power_total_w = power_charging_w
                elif power_total_w == 0.0 and slow.get("discharge_rate_mw", 0) > 0:
                    power_total_w = float(slow["discharge_rate_mw"]) / 1000.0

                # Health score
                health = 100
                if cpu_usage > 90: health -= 15
                elif cpu_usage > 80: health -= 8
                if ram.percent > 90: health -= 20
                elif ram.percent > 80: health -= 10
                if slow["disk_usage_percent"] > 95: health -= 15
                elif slow["disk_usage_percent"] > 90: health -= 8
                gpu_temp = gpu.get("temperature", 0)
                if gpu_temp > 85: health -= 10
                elif gpu_temp > 75: health -= 4
                if not slow["network_connected"]: health -= 25
                health = max(0, min(100, health))

                with self.lock:
                    self.live_metrics = {
                        "cpu_usage": cpu_usage, "cpu_frequency": cpu_freq, "cpu_temp": slow["cpu_temp"],
                        "gpu_name": gpu["name"], "gpu_usage": gpu["usage_percent"],
                        "gpu_memory_usage": gpu["memory_usage_percent"],
                        "gpu_memory_total": gpu["memory_total_mb"], "gpu_memory_used": gpu["memory_used_mb"],
                        "gpu_temp": f"{gpu['temperature']} °C" if gpu.get("temperature") else "N/A",
                        "ram_total_gb": _gb(ram.total), "ram_used_gb": _gb(ram.used),
                        "ram_avail_gb": _gb(ram.available), "ram_usage_percent": ram.percent,
                        "disk_usage_percent": slow["disk_usage_percent"],
                        "disk_total_gb": slow["disk_total_gb"], "disk_used_gb": slow["disk_used_gb"],
                        "disk_free_gb": slow["disk_free_gb"],
                        "disk_read_speed": slow["disk_read_speed"], "disk_write_speed": slow["disk_write_speed"],
                        "net_upload_speed": slow["net_upload_speed"], "net_download_speed": slow["net_download_speed"],
                        "net_bytes_sent": slow["net_bytes_sent"], "net_bytes_received": slow["net_bytes_received"],
                        "system_uptime": slow["system_uptime"], "boot_time": slow["boot_time"],
                        "current_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "health_score": health, "network_connected": slow["network_connected"],
                        "battery_percent": slow["battery_percent"], "battery_plugged": slow["battery_plugged"],
                        "battery_time_left": slow["battery_time_left"], "battery_time_used": slow["battery_time_used"],
                        "power_total_w": round(power_total_w, 2), "power_cpu_w": round(power_cpu_w, 2),
                        "power_gpu_w": round(gpu_power_w, 2), "power_charging_w": round(power_charging_w, 2),
                    }

                # Update process cache every ~3 seconds
                self.process_tick += 1
                if self.process_tick >= 15 or not self.process_cache:
                    self.process_tick = 0
                    threading.Thread(target=self._update_process_cache, daemon=True).start()
            except Exception as e:
                print(f"Error in monitor loop: {e}")
            time.sleep(self.refresh_interval)

    def get_live_metrics(self):
        with self.lock:
            return self.live_metrics.copy()

    def _update_process_cache(self):
        curr_time = time.time()
        with self.lock:
            sys_up = self.live_metrics.get("net_upload_speed", 0.0)
            sys_down = self.live_metrics.get("net_download_speed", 0.0)

        processes, new_prev_io, total_conns = [], {}, 0
        raw = []

        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info', 'num_threads', 'status', 'exe', 'io_counters']):
            try:
                pi = proc.info
                try:
                    conns = len(proc.net_connections())
                except Exception:
                    conns = 0
                total_conns += conns
                raw.append((pi, conns))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        for pi, conns in raw:
            pid = pi["pid"]
            io = pi["io_counters"]
            read_speed = write_speed = 0.0
            if io:
                if pid in self.prev_proc_io:
                    prev_t, prev_r, prev_w = self.prev_proc_io[pid]
                    dt = curr_time - prev_t
                    if dt > 0:
                        read_speed = max(0.0, (io.read_bytes - prev_r) / dt)
                        write_speed = max(0.0, (io.write_bytes - prev_w) / dt)
                new_prev_io[pid] = (curr_time, io.read_bytes, io.write_bytes)

            net_up = net_down = 0.0
            if total_conns > 0 and conns > 0:
                frac = conns / total_conns
                net_up, net_down = sys_up * frac, sys_down * frac

            mem = pi["memory_info"]
            processes.append({
                "pid": pid, "name": pi["name"] or "Unknown",
                "cpu_usage": round(pi["cpu_percent"] or 0, 1),
                "memory_mb": _mb(mem.rss) if mem else 0,
                "commit_mb": _mb(mem.vms) if mem else 0,
                "threads": pi["num_threads"] or 1, "status": pi["status"] or "unknown",
                "path": pi["exe"] or "N/A",
                "read_speed": round(read_speed, 1), "write_speed": round(write_speed, 1),
                "net_up_speed": round(net_up, 1), "net_down_speed": round(net_down, 1),
                "connections": conns,
            })

        self.prev_proc_io = new_prev_io
        with self.lock:
            self.process_cache = processes

    def get_process_list(self):
        with self.lock:
            return self.process_cache.copy()

    def get_event_logs(self, limit=1000):
        severity_map = {1: "Error", 2: "Warning", 4: "Information", 8: "Audit Success", 16: "Audit Failure"}
        events_list = []
        for logtype in ['System', 'Application']:
            try:
                hand = win32evtlog.OpenEventLog('localhost', logtype)
                flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
                count = 0
                per_log = limit // 2
                while count < per_log:
                    events = win32evtlog.ReadEventLog(hand, flags, 0)
                    if not events:
                        break
                    for ev in events:
                        if count >= per_log:
                            break
                        count += 1
                        time_gen = "N/A"
                        try:
                            time_gen = ev.TimeGenerated.strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            pass
                        try:
                            msg = win32evtlogutil.SafeFormatMessage(ev, logtype)
                            msg = " ".join(msg.split()) if msg else "No description"
                        except Exception:
                            msg = f"Event ID {ev.EventID & 0xFFFF} from {ev.SourceName}."
                        events_list.append({
                            "log_type": logtype, "timestamp": time_gen,
                            "source": ev.SourceName or "Unknown",
                            "event_id": ev.EventID & 0xFFFF,
                            "severity": severity_map.get(ev.EventType, f"Unknown ({ev.EventType})"),
                            "message": msg,
                        })
            except Exception as e:
                print(f"Error reading event log {logtype}: {e}")

        events_list.sort(key=lambda x: x["timestamp"], reverse=True)
        return events_list[:limit]


if __name__ == "__main__":
    print("Testing SystemMonitor data collection...")
    monitor = SystemMonitor()
    time.sleep(1.5)
    print("Live Metrics:")
    for k, v in monitor.get_live_metrics().items():
        print(f"  {k}: {v}")
    print("\nStatic Info:")
    for k, v in monitor.static_info.items():
        if k not in ("storage_devices", "network_adapters"):
            print(f"  {k}: {v}")
    print(f"\nStorage Devices: {len(monitor.static_info['storage_devices'])}")
    print(f"Network Adapters: {len(monitor.static_info['network_adapters'])}")
    print(f"Installed Apps: {len(monitor.installed_software)}")
    print(f"Update History Cache: {len(monitor.update_history)}")
    print(f"Processes Sample: {len(monitor.get_process_list())}")
    print(f"Event Log Sample: {len(monitor.get_event_logs(10))}")
    monitor.stop()
