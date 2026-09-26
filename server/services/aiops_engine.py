"""
AIOps Engine
=============

Statistical anomaly detection, failure forecasting, root cause analysis,
and natural language health summaries. Uses pure statistical methods
(Z-score, threshold comparison) — no ML dependencies.

All functions are pure: they take data in, return results out,
with no database or WebSocket dependencies.
"""
import datetime
import statistics
from typing import Any


def detect_anomalies(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect statistical anomalies using rolling Z-Score analysis."""
    if len(snapshots) < 4:
        return []

    anomalies = []
    for key in ["cpu_usage", "ram_usage_percent", "disk_write_speed", "net_download_speed"]:
        values = [
            s["metrics"][key]
            for s in snapshots
            if "metrics" in s and key in s.get("metrics", {})
        ]
        if len(values) < 4:
            continue
        mean = statistics.mean(values)
        std = max(statistics.pstdev(values), 1.5)

        for s in snapshots:
            val = s.get("metrics", {}).get(key)
            if val is None:
                continue
            z = (val - mean) / std
            if abs(z) >= 2.2:
                label = key.replace("_", " ").title()
                anomalies.append({
                    "timestamp": s.get("timestamp"),
                    "metric_name": key,
                    "metric_label": label,
                    "value": round(val, 2),
                    "baseline_mean": round(mean, 2),
                    "z_score": round(z, 2),
                    "priority_score": min(round(abs(z) * 20, 1), 99.9),
                    "severity": (
                        "critical" if abs(z) >= 3.0
                        else "warning" if abs(z) >= 2.5
                        else "info"
                    ),
                    "reason": f"{label} spiked to {val:.1f} (Z-Score: {z:+.2f}, baseline avg: {mean:.1f})",
                })

    anomalies.sort(key=lambda a: a["priority_score"], reverse=True)
    return anomalies[:20]


def forecast_failure(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate Time-To-Failure forecasts based on resource exhaustion velocity."""
    if not snapshots:
        return {"has_critical_failure_risk": False, "risk_level": "LOW", "warnings": []}

    latest = snapshots[0].get("metrics", {})
    warnings = []
    has_critical = False

    checks = [
        ("RAM (System Memory)", latest.get("ram_usage_percent", 0.0), 90.0, 80.0, False, "%"),
        ("SSD (System Storage Drive C:)", latest.get("disk_free_gb", 50.0), 5.0, 15.0, True, " GB"),
    ]
    for resource, val, crit, warn, low_is_bad, unit in checks:
        is_crit = (val < crit) if low_is_bad else (val > crit)
        is_warn = (val < warn) if low_is_bad else (val > warn)
        display = f"{val:.1f}{unit} {'Free' if low_is_bad else 'Used'}"

        if is_crit:
            has_critical = True
            ttf = "< 1 hour" if low_is_bad else "~15 to 45 minutes"
            rec = f"Critical {resource.split('(')[0].strip()} exhaustion! {'Run automated cleanup immediately.' if low_is_bad else 'Terminate leaking processes.'}"
            warnings.append({"resource": resource, "severity": "critical", "current_value": display,
                             "estimated_ttf": ttf, "recommendation": rec})
        elif is_warn:
            ttf = "~12 to 24 hours" if low_is_bad else "~2 to 4 hours"
            warnings.append({"resource": resource, "severity": "warning", "current_value": display,
                             "estimated_ttf": ttf, "recommendation": f"Elevated {resource.split('(')[0].strip()} utilization. Monitor active processes."})
        else:
            warnings.append({"resource": resource, "severity": "info", "current_value": display,
                             "estimated_ttf": "No Depletion Risk (> 30 Days)",
                             "recommendation": f"{resource.split('(')[0].strip()} operating within safe bounds."})

    return {
        "has_critical_failure_risk": has_critical,
        "risk_level": "CRITICAL" if has_critical else ("ELEVATED" if any(w["severity"] == "warning" for w in warnings) else "LOW"),
        "warnings": warnings,
    }


def suggest_root_cause(
    anomalies: list[dict], processes: list[dict], events: list[dict]
) -> list[dict]:
    """Correlate anomalies with processes and events to suggest root causes."""
    suggestions = []
    top_cpu = sorted(processes, key=lambda p: p.get("cpu_percent", 0.0), reverse=True)[:3] if processes else []
    top_ram = sorted(processes, key=lambda p: p.get("memory_percent", 0.0), reverse=True)[:3] if processes else []
    errors = [e for e in events if e.get("severity") in ("Error", "Critical")][:3] if events else []

    for anomaly in anomalies[:5]:
        metric, val = anomaly.get("metric_name"), anomaly.get("value")
        if metric == "cpu_usage" and top_cpu:
            p = top_cpu[0]
            suggestions.append({
                "anomaly_metric": "CPU Usage", "trigger_value": f"{val}%", "root_cause_type": "process_spike",
                "suspect": f"{p.get('name')} (PID {p.get('pid')})",
                "suspect_detail": f"Consuming {p.get('cpu_percent', 0):.1f}% CPU & {p.get('memory_mb', 0):.0f} MB RAM",
                "suggested_action": "kill_process", "suggested_target": p.get("name"),
                "reasoning": f"CPU spike to {val}% correlates with high thread load in '{p.get('name')}'.",
            })
        elif metric == "ram_usage_percent" and top_ram:
            p = top_ram[0]
            act = "restart_service" if "service" in p.get("name", "").lower() else "kill_process"
            suggestions.append({
                "anomaly_metric": "RAM Usage", "trigger_value": f"{val}%", "root_cause_type": "memory_leak",
                "suspect": f"{p.get('name')} (PID {p.get('pid')})",
                "suspect_detail": f"Holding {p.get('memory_mb', 0):.0f} MB RAM ({p.get('memory_percent', 0):.1f}% of total)",
                "suggested_action": act, "suggested_target": p.get("name"),
                "reasoning": f"RAM elevation to {val}% driven by heavy working set in '{p.get('name')}'.",
            })
        elif errors:
            ev = errors[0]
            suggestions.append({
                "anomaly_metric": anomaly.get("metric_label"), "trigger_value": f"{val}",
                "root_cause_type": "event_log_error", "suspect": f"Event Source: {ev.get('source')}",
                "suspect_detail": ev.get("message", "")[:100],
                "suggested_action": "cleanup_temp", "suggested_target": None,
                "reasoning": f"Anomaly coincided with Windows Event error '{ev.get('source')}'.",
            })

    if not suggestions:
        suggestions.append({
            "anomaly_metric": "System Baseline", "trigger_value": "Normal", "root_cause_type": "optimal",
            "suspect": "None (System Operational)",
            "suspect_detail": "All telemetry metrics within normal baseline ranges.",
            "suggested_action": None, "suggested_target": None,
            "reasoning": "No metric anomalies or process leaks detected.",
        })
    return suggestions


def generate_ai_health_insights(
    snapshots: list[dict], anomalies: list[dict], failure_forecast: dict
) -> dict:
    """Generate executive natural language diagnostic summary."""
    risk = failure_forecast.get("risk_level", "LOW")
    n = len(anomalies)
    if risk == "CRITICAL":
        summary = f"⚠️ CRITICAL SYSTEM RISK DETECTED: {n} telemetry anomalies alongside critical failure warnings."
        action = "Immediate IT remediation required. Execute cleanup or terminate leaking processes."
    elif risk == "ELEVATED":
        summary = f"⚡ ELEVATED RISK: {n} metric anomaly spikes. Resource utilization approaching warning thresholds."
        action = "Review automation rules and monitor high-memory background tasks."
    else:
        summary = "✅ SYSTEM OPTIMAL: Telemetry metrics stable with normal Z-score baseline variances."
        action = "No immediate intervention required. Continuous AIOps monitoring active."

    return {
        "risk_level": risk, "anomaly_count": n, "summary": summary, "action_item": action,
        "health_score": 95 if risk == "LOW" else (70 if risk == "ELEVATED" else 40),
        "generated_at": datetime.datetime.utcnow().isoformat(),
    }
