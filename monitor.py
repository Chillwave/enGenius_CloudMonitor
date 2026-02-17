#!/usr/bin/env python3
"""
EnGenius Cloud Device Status Monitor
Monitors APs and switches for online/offline status changes

Usage:
    python3 monitor.py              Run once, export CSV
    python3 monitor.py --monitor    Continuous monitoring
    python3 monitor.py --daemon     Daemon mode for systemd
    python3 monitor.py --test-smtp  Test SMTP connection
"""

import sys
import os
import csv
import time
import json
import argparse
from datetime import datetime, timedelta

from config import (
    CHECK_INTERVAL, STATUS_FILE,
    load_api_key, load_smtp_config
)
from engenius_api import EnGeniusAPI
from smtp_engine import send_alert, test_connection
from wan_tracker import check_wan_changes, export_wan_csv, extract_wan_ips

# =============================================================================
# GLOBALS
# =============================================================================
LOG_FILE = None
SMTP_CONFIG = None
API = None
DAEMON_MODE = False


def output(msg):
    """Print with flush for journald compatibility."""
    print(msg, flush=True)


# =============================================================================
# LOGGING
# =============================================================================
def init_log_file():
    global LOG_FILE
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    LOG_FILE = os.path.join(log_dir, f"device_monitor_log_{timestamp}.txt")
    with open(LOG_FILE, 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("EnGenius Device Monitor Log\n")
        f.write("=" * 80 + "\n")
        f.write(f"Started:        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Check Interval: {CHECK_INTERVAL} seconds ({CHECK_INTERVAL // 60} min)\n")
        f.write("=" * 80 + "\n\n")
    output(f"[INFO] Log file: {LOG_FILE}")


def log(level, message):
    if LOG_FILE:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, 'a') as f:
            f.write(f"[{ts}] [{level}] {message}\n")


# =============================================================================
# STATUS CACHE
# =============================================================================
def load_previous():
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, 'r') as f:
                data = json.load(f)
            output(f"[INFO] Loaded previous state: {len(data)} devices")
            return data
        except:
            pass
    output("[INFO] No previous state, starting fresh")
    return {}


def save_current(status):
    with open(STATUS_FILE, 'w') as f:
        json.dump(status, f, indent=2)


# =============================================================================
# HELPERS
# =============================================================================
def format_duration(td):
    """Format a timedelta as human-readable duration."""
    total_seconds = int(td.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or not parts:
        parts.append(f"{minutes}m")
    
    return " ".join(parts)


def sort_offline_newest_first(devices):
    """Sort offline devices by last_seen, newest first. Empty last_seen goes last."""
    def sort_key(d):
        ls = d.get("last_seen", "")
        if not ls:
            return ""
        return ls
    return sorted(devices, key=sort_key, reverse=True)


def print_outages(offline_devices):
    """Print current outage list, sorted newest to oldest."""
    if not offline_devices:
        output("[INFO] Current outages: None")
        return
    
    sorted_offline = sort_offline_newest_first(offline_devices)
    output(f"[INFO] Current outages ({len(sorted_offline)}):")
    for d in sorted_offline:
        last = d.get("last_seen") or d.get("last_seen_str") or "N/A"
        name = d.get("device_name") or d.get("name", "?")
        dtype = d.get("device_type") or d.get("type", "?")
        network = d.get("network", "?")
        wan = d.get("wan_ip", "")
        wan_str = f" WAN: {wan}" if wan else ""
        output(f"         [{dtype}] {name} ({network}){wan_str} last seen: {last}")


# =============================================================================
# ALERT PROCESSING
# =============================================================================
def process_alert(alert_type, devices, all_devices=None):
    """Console output + log + SMTP for status changes."""
    
    lines = []
    for d in devices:
        line = f"[{d['type']}] {d['name']} ({d['network']})"
        if d.get('wan_ip'):
            line += f" WAN: {d['wan_ip']}"
        if alert_type == "ONLINE" and d.get('outage_duration'):
            line += f" (was offline for {d['outage_duration']})"
        lines.append(line)
    
    summary = f"{len(devices)} device(s) went {alert_type}:\n" + "\n".join(f"  - {l}" for l in lines)
    
    # Console
    output("")
    output("=" * 70)
    output(f"ALERT: {len(devices)} DEVICE(S) WENT {alert_type}")
    output("=" * 70)
    for d in devices:
        output(f"  Type:      {d['type']}")
        output(f"  Name:      {d['name']}")
        output(f"  Network:   {d['network']}")
        if d.get('wan_ip'):
            output(f"  WAN IP:    {d['wan_ip']}")
        if alert_type == "ONLINE" and d.get('outage_duration'):
            output(f"  Outage:    {d['outage_duration']}")
        if d.get('last_seen'):
            output(f"  Last Seen: {d['last_seen']}")
        output("-" * 40)
    output("=" * 70)
    
    # Log
    log("ALERT", f"{len(devices)} device(s) went {alert_type}")
    for d in devices:
        wan = f" WAN:{d['wan_ip']}" if d.get('wan_ip') else ""
        dur = f" outage:{d['outage_duration']}" if d.get('outage_duration') else ""
        log("ALERT", f"  [{d['type']}] {d['name']} ({d['network']}){wan}{dur}")
    
    # SMTP with device list and stats
    stats = None
    if all_devices:
        stats = {
            "total": len(all_devices),
            "online": len([x for x in all_devices if x["status"] == "online"]),
            "offline": len([x for x in all_devices if x["status"] == "offline"]),
        }
    
    send_alert(
        SMTP_CONFIG,
        f"{len(devices)} device(s) went {alert_type}",
        summary,
        devices=devices,
        stats=stats,
        log_fn=log,
    )


def process_inventory_change(change_type, devices):
    """Console output + log for new/removed devices."""
    
    output("")
    output("=" * 70)
    output(f"INVENTORY: {len(devices)} DEVICE(S) {change_type}")
    output("=" * 70)
    for d in devices:
        output(f"  Type:      {d['type']}")
        output(f"  Name:      {d['name']}")
        output(f"  Network:   {d['network']}")
        output(f"  Status:    {d['status']}")
        if d.get('wan_ip'):
            output(f"  WAN IP:    {d['wan_ip']}")
        output("-" * 40)
    output("=" * 70)
    
    log("INVENTORY", f"{len(devices)} device(s) {change_type}")
    for d in devices:
        log("INVENTORY", f"  [{d['type']}] {d['name']} ({d['network']}) status={d['status']}")


def process_wan_change(changes):
    """Console output + log + SMTP for WAN IP changes."""
    
    output("")
    output("=" * 70)
    output(f"WAN IP CHANGE: {len(changes)} SITE(S)")
    output("=" * 70)
    for c in changes:
        output(f"  Network: {c['network']}")
        output(f"  Old IP:  {c['old_ip']}")
        output(f"  New IP:  {c['new_ip']}")
        output("-" * 40)
    output("=" * 70)
    
    # Log
    log("WAN_CHANGE", f"{len(changes)} site(s) changed WAN IP")
    for c in changes:
        log("WAN_CHANGE", f"  {c['network']}: {c['old_ip']} -> {c['new_ip']}")
    
    # SMTP
    body = f"{len(changes)} site(s) changed WAN IP:\n\n"
    for c in changes:
        body += f"  {c['network']}\n"
        body += f"    Old: {c['old_ip']}\n"
        body += f"    New: {c['new_ip']}\n\n"
    
    # Use send_alert with device-like format for consistency
    devices = []
    for c in changes:
        devices.append({
            "type": "WAN",
            "name": c["network"],
            "network": c["network"],
            "wan_ip": f"{c['old_ip']} -> {c['new_ip']}",
            "last_seen": "",
        })
    
    send_alert(
        SMTP_CONFIG,
        f"{len(changes)} WAN IP change(s) detected",
        body,
        devices=devices,
        stats=None,
        log_fn=log,
    )


# =============================================================================
# RUN ONCE
# =============================================================================
def run_once():
    output("")
    output("=" * 70)
    output("EnGenius Cloud Device Status Monitor")
    output(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    output("=" * 70)
    output("")
    
    all_devices = API.get_all_device_status()
    
    if not all_devices:
        output("[ERROR] No devices found")
        return
    
    online = [d for d in all_devices if d["status"] == "online"]
    offline = [d for d in all_devices if d["status"] == "offline"]
    
    # Type counts
    types = {}
    for d in all_devices:
        t = d["device_type"]
        if t not in types:
            types[t] = {"total": 0, "online": 0, "offline": 0}
        types[t]["total"] += 1
        if d["status"] == "online":
            types[t]["online"] += 1
        elif d["status"] == "offline":
            types[t]["offline"] += 1
    
    output("")
    output("=" * 70)
    output("STATUS SUMMARY")
    output("=" * 70)
    output(f"  Total:   {len(all_devices)}")
    output(f"  Online:  {len(online)}")
    output(f"  Offline: {len(offline)}")
    output("")
    for t, c in types.items():
        output(f"  {t}: {c['total']} total, {c['online']} online, {c['offline']} offline")
    output("=" * 70)
    
    if offline:
        output("")
        output("=" * 70)
        output(f"OFFLINE DEVICES ({len(offline)})")
        output("=" * 70)
        sorted_offline = sort_offline_newest_first(offline)
        for d in sorted_offline:
            output(f"  [{d['device_type']}] {d['device_name']}")
            output(f"      Network:   {d['network']}")
            output(f"      Model:     {d['model']}")
            output(f"      MAC:       {d['mac']}")
            output(f"      WAN IP:    {d.get('wan_ip') or 'N/A'}")
            output(f"      Last Seen: {d['last_seen'] or 'N/A'}")
            output("")
        output("=" * 70)
    
    # Export CSV
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"engenius_device_status_{ts}.csv"
    
    fields = [
        "organization", "network", "device_type", "device_name",
        "mac", "model", "serial_number", "status", "wan_ip", "last_seen"
    ]
    
    with open(filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_devices)
    
    output(f"[INFO] Exported: {filename}")
    
    # Export WAN data CSV
    wan_data = extract_wan_ips(all_devices)
    export_wan_csv(wan_data)
    output(f"[INFO] WAN data: current_WanData.csv")
    
    status = {}
    for d in all_devices:
        status[d["mac"]] = {
            "status": d["status"],
            "name": d["device_name"],
            "network": d["network"],
            "type": d["device_type"],
            "last_seen": d["last_seen"],
            "wan_ip": d.get("wan_ip", ""),
        }
    save_current(status)
    output(f"[INFO] State cached: {STATUS_FILE}")


# =============================================================================
# CONTINUOUS MONITOR
# =============================================================================
def run_monitor(interval=None):
    if interval is None:
        interval = CHECK_INTERVAL
    
    init_log_file()
    
    output("")
    output("=" * 70)
    output(f"EnGenius Device Monitor - {'DAEMON' if DAEMON_MODE else 'CONTINUOUS'} MODE")
    output("=" * 70)
    output(f"Devices:   APs, Switches")
    output(f"Interval:  {interval} seconds ({interval // 60} min)")
    output(f"Log:       {LOG_FILE}")
    output(f"Cache:     {STATUS_FILE}")
    output(f"SMTP:      {'ENABLED' if SMTP_CONFIG and SMTP_CONFIG.get('enabled') else 'DISABLED'}")
    output("=" * 70)
    if not DAEMON_MODE:
        output("Ctrl+C to stop")
        output("=" * 70)
    
    previous = load_previous()
    check_num = 0
    
    while True:
        try:
            check_num += 1
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            output(f"--- CHECK #{check_num} | {ts} ---")
            
            all_devices = API.get_all_device_status()
            
            if not all_devices:
                output("[WARN] No devices found, retrying next interval")
                time.sleep(interval)
                continue
            
            # Build current state
            current = {}
            for d in all_devices:
                current[d["mac"]] = {
                    "status": d["status"],
                    "name": d["device_name"],
                    "network": d["network"],
                    "type": d["device_type"],
                    "last_seen": d["last_seen"],
                    "wan_ip": d.get("wan_ip", ""),
                    "offline_since": None,
                }
            
            # Detect status changes
            went_offline = []
            came_online = []
            
            for mac, info in current.items():
                prev = previous.get(mac)
                if prev:
                    if prev["status"] == "online" and info["status"] == "offline":
                        # Mark when it went offline
                        info["offline_since"] = datetime.now().isoformat()
                        went_offline.append(info)
                    elif prev["status"] == "offline" and info["status"] == "online":
                        # Calculate how long it was offline
                        if prev.get("offline_since"):
                            try:
                                offline_start = datetime.fromisoformat(prev["offline_since"])
                                elapsed = datetime.now() - offline_start
                                info["outage_duration"] = format_duration(elapsed)
                            except:
                                info["outage_duration"] = "unknown"
                        else:
                            info["outage_duration"] = "unknown"
                        came_online.append(info)
                    elif info["status"] == "offline" and prev.get("offline_since"):
                        # Carry forward offline_since for devices still offline
                        info["offline_since"] = prev["offline_since"]
            
            # Detect new and removed devices
            current_macs = set(current.keys())
            previous_macs = set(previous.keys())
            
            new_macs = current_macs - previous_macs
            removed_macs = previous_macs - current_macs
            
            new_devices = [current[mac] for mac in new_macs]
            removed_devices = [previous[mac] for mac in removed_macs]
            
            # Stats
            online_count = len([d for d in all_devices if d["status"] == "online"])
            offline_count = len([d for d in all_devices if d["status"] == "offline"])
            
            types = {}
            for d in all_devices:
                types[d["device_type"]] = types.get(d["device_type"], 0) + 1
            type_str = ", ".join(f"{t}={c}" for t, c in types.items())
            
            output(f"[INFO] Total: {len(all_devices)} | Online: {online_count} | Offline: {offline_count}")
            output(f"[INFO] Types: {type_str}")
            
            log("CHECK", f"Total={len(all_devices)} Online={online_count} Offline={offline_count} {type_str}")
            
            # First check: show current outages. After that: only changes.
            if check_num == 1:
                offline_devices = [d for d in all_devices if d["status"] == "offline"]
                print_outages(offline_devices)
            
            # Check for WAN IP changes
            wan_changes, wan_new, wan_removed = check_wan_changes(all_devices, log_fn=log)
            
            # Changes
            has_changes = went_offline or came_online or new_devices or removed_devices or wan_changes
            
            if went_offline:
                process_alert("OFFLINE", went_offline, all_devices)
            if came_online:
                process_alert("ONLINE", came_online, all_devices)
            if new_devices and previous:
                process_inventory_change("ADDED", new_devices)
            if removed_devices:
                process_inventory_change("REMOVED", removed_devices)
            if wan_changes:
                process_wan_change(wan_changes)
            if not has_changes:
                if check_num == 1:
                    output("[INFO] Baseline captured")
                else:
                    output("[INFO] Changes: None")
            
            previous = current
            save_current(current)
            
            next_check = (datetime.now() + timedelta(seconds=interval)).strftime('%Y-%m-%d %H:%M:%S')
            output(f"[INFO] Next check at {next_check}")
            
            if not DAEMON_MODE:
                # Countdown so console doesn't look frozen
                remaining = interval
                while remaining > 0:
                    if remaining > 60:
                        mins = remaining // 60
                        print(f"[WAIT] {mins}m remaining...", end='\r', flush=True)
                        time.sleep(60)
                        remaining -= 60
                    else:
                        print(f"[WAIT] {remaining}s remaining...  ", end='\r', flush=True)
                        time.sleep(remaining)
                        remaining = 0
                print(" " * 40, end='\r', flush=True)
            else:
                time.sleep(interval)
            
        except KeyboardInterrupt:
            output("")
            output("=" * 70)
            output("Monitor stopped")
            output("=" * 70)
            log("INFO", "Monitor stopped by user")
            break
        except Exception as e:
            output(f"[ERROR] {e}")
            log("ERROR", str(e))
            time.sleep(interval)


# =============================================================================
# ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EnGenius Device Status Monitor")
    parser.add_argument("--once", action="store_true", help="Run once and exit (default)")
    parser.add_argument("--monitor", action="store_true", help="Continuous monitoring")
    parser.add_argument("--daemon", action="store_true", help="Daemon mode (no countdown, clean journal output)")
    parser.add_argument("--interval", type=int, default=None, help=f"Seconds between checks (default: {CHECK_INTERVAL})")
    parser.add_argument("--test-smtp", action="store_true", help="Test SMTP connection and exit")
    
    args = parser.parse_args()
    
    # Daemon implies monitor
    if args.daemon:
        args.monitor = True
        DAEMON_MODE = True
    
    # Load config
    api_key = load_api_key()
    SMTP_CONFIG = load_smtp_config()
    API = EnGeniusAPI(api_key)
    
    if args.test_smtp and not args.monitor:
        test_connection(SMTP_CONFIG)
    elif args.monitor:
        if args.test_smtp:
            output("[INFO] Testing SMTP before starting monitor...")
            test_connection(SMTP_CONFIG)
            output("")
        run_monitor(args.interval)
    else:
        run_once()
