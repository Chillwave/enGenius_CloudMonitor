"""
engenius_api.py - EnGenius Cloud API client
Handles authentication, requests, and device inventory fetching
"""

import requests
import time
from datetime import datetime
from config import BASE_URL, MAX_RETRIES, RETRY_DELAY


class EnGeniusAPI:
    def __init__(self, api_key):
        self.session = requests.Session()
        self.session.headers.update({
            "api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        })
    
    def get(self, endpoint, params=None):
        """Make GET request with retry logic"""
        url = f"{BASE_URL}{endpoint}"
        
        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.get(url, params=params, timeout=30)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 406:
                    print(f"[ERROR] API returned 406 Not Acceptable for {endpoint}")
                    print(f"[ERROR] This usually means expired API key or IP not authorized")
                    print(f"[ERROR] Regenerate your API key or check IP allow list in EnGenius Cloud")
                    return None
                elif resp.status_code == 503:
                    if attempt < MAX_RETRIES - 1:
                        print(f"[WARN] API returned 503, retry {attempt + 1}/{MAX_RETRIES}...")
                        time.sleep(RETRY_DELAY)
                        continue
                else:
                    print(f"[WARN] API returned {resp.status_code} for {endpoint}")
                return None
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    print(f"[WARN] Request failed: {e}, retry {attempt + 1}/{MAX_RETRIES}...")
                    time.sleep(RETRY_DELAY)
                else:
                    print(f"[ERROR] Request failed after {MAX_RETRIES} attempts: {e}")
        return None
    
    def get_all_device_status(self):
        """
        Fetch status of all devices across all networks.
        
        Device types pulled:
          - APs:       /devices/aps
          - Switches:  /devices/switches
        
        Note: Switch extenders have no dedicated list endpoint and no
        online/offline status in the inventory API. Use the inventory
        diag tool or license export to track them separately.
        
        Returns list of device dicts.
        """
        all_devices = []
        
        # ----- Get orgs -----
        print("[INFO] Fetching organizations...")
        orgs = self.get("/user/orgs")
        if not orgs:
            print("[ERROR] Could not get organizations")
            return []
        
        if isinstance(orgs, dict):
            orgs = [orgs]
        
        print(f"[INFO] Found {len(orgs)} organization(s)")
        
        for org in orgs:
            org_id = org.get("id") or org.get("_id")
            org_name = org.get("name", "Unknown")
            print(f"[INFO] Organization: {org_name}")
            
            # ----- Get hierarchy views -----
            hvs = self.get(f"/orgs/{org_id}/hvs")
            if not hvs:
                print(f"[WARN] No hierarchy views found for {org_name}")
                continue
            
            if isinstance(hvs, dict):
                hvs = [hvs]
            
            for hv in hvs:
                hv_id = hv.get("id") or hv.get("_id")
                hv_name = hv.get("name", "root")
                networks = hv.get("networks", [])
                
                print(f"[INFO]   Hierarchy: {hv_name} ({len(networks)} networks)")
                
                for network in networks:
                    net_id = network.get("id") or network.get("_id")
                    net_name = network.get("name", "Unknown")
                    
                    ap_count = 0
                    sw_count = 0
                    
                    # ---- APs ----
                    aps = self.get(f"/orgs/{org_id}/hvs/{hv_id}/networks/{net_id}/devices/aps", params={"count": 500})
                    if aps:
                        ap_list = aps.get("aps", aps.get("devices", [])) if isinstance(aps, dict) else aps
                        for ap in ap_list:
                            info = ap.get("information", {})
                            status = info.get("status", "unknown") if isinstance(info, dict) else "unknown"
                            last_seen = info.get("last_seen") if isinstance(info, dict) else None
                            
                            last_seen_str = ""
                            if last_seen:
                                try:
                                    last_seen_str = datetime.fromtimestamp(last_seen / 1000).strftime("%Y-%m-%d %H:%M:%S")
                                except:
                                    pass
                            
                            wan_ip = info.get("wan_ip", "") if isinstance(info, dict) else ""
                            
                            all_devices.append({
                                "organization": org_name,
                                "network": net_name,
                                "device_type": "AP",
                                "device_name": ap.get("name", ""),
                                "mac": ap.get("mac", ""),
                                "model": ap.get("model", ""),
                                "serial_number": ap.get("serial_number", ""),
                                "status": status,
                                "last_seen": last_seen_str,
                                "wan_ip": wan_ip,
                            })
                            ap_count += 1
                    
                    # ---- Switches ----
                    switches = self.get(f"/orgs/{org_id}/hvs/{hv_id}/networks/{net_id}/devices/switches", params={"count": 500})
                    if switches:
                        sw_list = switches.get("switches", switches.get("devices", [])) if isinstance(switches, dict) else switches
                        for switch in sw_list:
                            info = switch.get("information", {})
                            status = info.get("status", "unknown") if isinstance(info, dict) else "unknown"
                            last_seen = info.get("last_seen") if isinstance(info, dict) else None
                            
                            last_seen_str = ""
                            if last_seen:
                                try:
                                    last_seen_str = datetime.fromtimestamp(last_seen / 1000).strftime("%Y-%m-%d %H:%M:%S")
                                except:
                                    pass
                            
                            wan_ip = info.get("wan_ip", "") if isinstance(info, dict) else ""
                            
                            all_devices.append({
                                "organization": org_name,
                                "network": net_name,
                                "device_type": "Switch",
                                "device_name": switch.get("name", ""),
                                "mac": switch.get("mac", ""),
                                "model": switch.get("model", ""),
                                "serial_number": switch.get("serial_number", ""),
                                "status": status,
                                "last_seen": last_seen_str,
                                "wan_ip": wan_ip,
                            })
                            sw_count += 1
                    
                    if ap_count or sw_count:
                        print(f"[INFO]     {net_name}: {ap_count} APs, {sw_count} switches")
        
        print(f"[INFO] Total devices found: {len(all_devices)}")
        
        # Type breakdown
        types = {}
        for d in all_devices:
            types[d["device_type"]] = types.get(d["device_type"], 0) + 1
        for t, c in types.items():
            print(f"[INFO]   {t}: {c}")
        
        return all_devices
