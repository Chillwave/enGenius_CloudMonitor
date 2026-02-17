"""
wan_tracker.py - WAN IP change detection module
Tracks WAN IPs per network and detects changes.
Called by monitor.py using existing device data.
"""

import os
import json
import csv
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WAN_STATUS_FILE = os.path.join(BASE_DIR, "wan_status.json")
WAN_CSV_FILE = os.path.join(BASE_DIR, "current_WanData.csv")


def load_wan_status():
    """Load previous WAN IP state."""
    if os.path.exists(WAN_STATUS_FILE):
        try:
            with open(WAN_STATUS_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_wan_status(status):
    """Save current WAN IP state."""
    with open(WAN_STATUS_FILE, 'w') as f:
        json.dump(status, f, indent=2)


def export_wan_csv(networks):
    """
    Export current WAN IPs to CSV for other programs to use.
    
    Args:
        networks: dict {network_name: wan_ip}
    """
    with open(WAN_CSV_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["network", "wan_ip", "last_updated"])
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for network, wan_ip in sorted(networks.items()):
            writer.writerow([network, wan_ip, timestamp])


def extract_wan_ips(devices):
    """
    Extract WAN IPs per network from device list.
    Takes first non-empty WAN IP found for each network.
    
    Args:
        devices: List of device dicts from API
        
    Returns:
        dict: {network_name: wan_ip}
    """
    networks = {}
    
    for d in devices:
        network = d.get("network", "")
        wan_ip = d.get("wan_ip", "")
        
        if not network:
            continue
        
        if network not in networks:
            networks[network] = wan_ip
        elif wan_ip and not networks[network]:
            # Prefer non-empty WAN IP
            networks[network] = wan_ip
    
    return networks


def check_wan_changes(devices, log_fn=None):
    """
    Check for WAN IP changes using device data.
    Also exports current WAN data to CSV.
    
    Args:
        devices: List of device dicts from API
        log_fn: Optional logging function(level, message)
        
    Returns:
        tuple: (changes, new_sites, removed_sites)
        - changes: List of {network, old_ip, new_ip}
        - new_sites: List of {network, wan_ip}
        - removed_sites: List of {network, wan_ip}
    """
    previous = load_wan_status()
    current = extract_wan_ips(devices)
    
    # Export to CSV for other programs
    export_wan_csv(current)
    
    changes = []
    new_sites = []
    removed_sites = []
    
    # Check for changes and new sites
    for network, new_ip in current.items():
        if network in previous:
            old_ip = previous[network]
            # Only alert if both have IPs and they differ
            if old_ip and new_ip and old_ip != new_ip:
                changes.append({
                    "network": network,
                    "old_ip": old_ip,
                    "new_ip": new_ip,
                })
                if log_fn:
                    log_fn("WAN_CHANGE", f"{network}: {old_ip} -> {new_ip}")
        else:
            new_sites.append({"network": network, "wan_ip": new_ip})
            if log_fn:
                log_fn("WAN_NEW", f"{network}: {new_ip}")
    
    # Check for removed sites
    for network, old_ip in previous.items():
        if network not in current:
            removed_sites.append({"network": network, "wan_ip": old_ip})
            if log_fn:
                log_fn("WAN_REMOVED", f"{network}: {old_ip}")
    
    # Save current state
    save_wan_status(current)
    
    return changes, new_sites, removed_sites


def get_wan_summary(devices):
    """
    Get summary of WAN IPs from device data.
    
    Args:
        devices: List of device dicts from API
        
    Returns:
        dict with counts and network list
    """
    networks = extract_wan_ips(devices)
    with_ip = sum(1 for ip in networks.values() if ip)
    
    return {
        "total": len(networks),
        "with_ip": with_ip,
        "without_ip": len(networks) - with_ip,
        "networks": networks,
    }
