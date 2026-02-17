# EnGenius Device Status Monitor

Monitors EnGenius Cloud APs, switches, and switch extenders for online/offline status and WAN IP changes . Alerts via console, log file, and optional SMTP email.

## Files

| File | Purpose |
|------|---------|
| `monitor.py` | Main entry point |
| `config.py` | Settings and config loading |
| `engenius_api.py` | EnGenius Cloud API client |
| `smtp_engine.py` | SMTP email alerts |
| `smtp_creds.example.json` | SMTP credential template (copy to `smtp_creds.json`) |
| `api_key.txt` | Your EnGenius API key (create this, gitignored) |
| `.gitignore` | Excludes keys, creds, and runtime data |

## Setup

```bash
pip install requests
echo "YOUR_API_KEY_HERE" > api_key.txt
```

## Usage

```bash
# Run once - show status, export CSV
python3 monitor.py

# Continuous monitoring (default 10 min interval)
python3 monitor.py --monitor

# Custom interval
python3 monitor.py --monitor --interval 300

# Test SMTP connection
python3 monitor.py --test-smtp
```

## Configuration

Edit `config.py` to change:

```python
CHECK_INTERVAL = 600  # seconds (600 = 10 min)
```

## SMTP Email Alerts

Copy the example config and edit with your credentials:

```bash
cp smtp_creds.example.json smtp_creds.json
```

Edit `smtp_creds.json`:

```json
{
    "enabled": true,
    "server": "your-smtp.com",
    "port": 587,
    "use_tls": true,
    "username": "your_username@domain.com",
    "password": "your_password_here",
    "from_addr": "alerts@yourdomain.com",
    "to_addr": "recipient@yourdomain.com",
    "subject_prefix": "[EnGenius Alert]"
}
```

Set `"enabled": true` to activate. Supports Office 365, Mimecast, and any TLS SMTP relay.

Test with: `python3 monitor.py --test-smtp`

## Monitored Device Types

| Type | Source | Endpoint |
|------|--------|----------|
| APs | Per-network API | `/devices/aps` |
| Switches | Per-network API | `/devices/switches` |
| Switch Extenders | Org inventory | `/inventory` (device_type: switch_extender) |

Switch extenders do not have a dedicated list endpoint in the EnGenius API. They are pulled from the organization inventory instead.

## Output Files

- `current_WanData.csv` - Refreshes with current data to provide WAN IP addresses for other applications in an easy format
- `device_status_cache.json` - State cache for change detection
- `device_monitor_log_TIMESTAMP.txt` - Alert log (monitor mode)

## Example Alerts

**WAN IP Change:**

```
Subject: [EnGenius Network Alert] 1 WAN IP change(s) detected

EnGenius Device Monitor - WAN IP Change Alert
==============================================
Timestamp: 2026-02-13 06:08:03

1 site(s) changed WAN IP:
  - NY-Lakewood-Office: 198.51.100.44 -> 203.0.113.87
```

**Devices Online:**

```
Subject: [EnGenius Network Alert] 2 device(s) came ONLINE

EnGenius Device Monitor - ONLINE Alert
========================================
Timestamp: 2026-02-13 01:31:28

2 device(s) came back ONLINE:
  - [Switch] NY-Lakewood-SW4 (NY-Lakewood) WAN: 192.0.2.150 (offline for 4h 13m)
  - [Switch] NY-Lakewood-SW3 (NY-Lakewood) WAN: 192.0.2.150 (offline for 4h 13m)

Current totals: 84 devices | 79 online | 5 offline
```

**Devices Offline:**

```
Subject: [EnGenius Network Alert] 2 device(s) went OFFLINE

EnGenius Device Monitor - OFFLINE Alert
========================================
Timestamp: 2026-02-12 21:17:38

2 device(s) went OFFLINE:
  - [Switch] NY-Lakewood-SW4 (NY-Lakewood) WAN: 192.0.2.150
  - [Switch] NY-Lakewood-SW3 (NY-Lakewood) WAN: 192.0.2.150

Current totals: 84 devices | 77 online | 7 offline
```

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| 406 Not Acceptable | Expired API key or unauthorized IP | Regenerate API key in EnGenius Cloud, check IP whitelist |
| 400 Bad Request | Wrong auth header | Script uses `api-key` header (not Bearer) |
| 402 Payment Required | No Pro license | API requires Pro feature plan |
| 503 Service Unavailable | API temporarily down | Script retries 3x automatically |
| No switch extenders in CSV | Normal if none deployed | They come from inventory, not `/devices/` endpoint |
