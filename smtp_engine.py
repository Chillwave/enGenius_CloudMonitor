"""
smtp_engine.py - SMTP email alert engine
Sends email alerts via TLS-enabled SMTP (Office 365, Mimecast, etc.)
Uses email_template.json for message formatting.
"""

import smtplib
import json
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

TEMPLATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_template.json")


def load_template():
    """Load email template. Returns defaults if file missing or broken."""
    defaults = {
        "offline_subject": "{count} device(s) went OFFLINE",
        "online_subject": "{count} device(s) came ONLINE",
        "wan_subject": "{count} WAN IP change(s) detected",
        "test_subject": "SMTP Test",
        "offline_body": [
            "Timestamp: {timestamp}",
            "",
            "{count} device(s) went OFFLINE:",
            "",
            "{device_list}",
        ],
        "online_body": [
            "Timestamp: {timestamp}",
            "",
            "{count} device(s) came ONLINE:",
            "",
            "{device_list}",
        ],
        "wan_body": [
            "Timestamp: {timestamp}",
            "",
            "{count} site(s) changed WAN IP:",
            "",
            "{device_list}",
        ],
        "device_format": "  - [{type}] {name} ({network}) WAN: {wan_ip} Last Seen: {last_seen}",
        "wan_format": "  - {name}: {wan_ip}",
        "test_body": [
            "SMTP Test",
            "Timestamp: {timestamp}",
            "If you received this, SMTP alerts are working.",
        ],
    }
    
    try:
        with open(TEMPLATE_FILE, 'r') as f:
            tmpl = json.load(f)
        for k, v in tmpl.items():
            if not k.startswith("_"):
                defaults[k] = v
        return defaults
    except FileNotFoundError:
        print(f"[SMTP] No email_template.json found, using defaults")
        return defaults
    except Exception as e:
        print(f"[SMTP] Error loading template: {e}, using defaults")
        return defaults


def format_device_list(devices, tmpl, is_wan=False):
    """Format a list of device dicts using the appropriate template."""
    if is_wan:
        fmt = tmpl.get("wan_format", "  - {name}: {wan_ip}")
    else:
        fmt = tmpl.get("device_format", "  - [{type}] {name} ({network})")
    
    lines = []
    for d in devices:
        # Build outage string if present
        outage = d.get("outage_duration", "")
        outage_str = f" (offline for {outage})" if outage else ""
        
        lines.append(fmt.format(
            type=d.get("type", "?"),
            name=d.get("name", "?"),
            network=d.get("network", "?"),
            wan_ip=d.get("wan_ip", "N/A"),
            last_seen=d.get("last_seen", "N/A"),
            status=d.get("status", "?"),
            mac=d.get("mac", "?"),
            outage_duration=outage,
            outage_str=outage_str,
        ))
    return "\n".join(lines)


def build_body(template_lines, **kwargs):
    """Join template lines and substitute variables."""
    text = "\n".join(template_lines)
    return text.format(**kwargs)


def send_alert(smtp_config, subject, message, devices=None, stats=None, log_fn=None):
    """
    Send an email alert via SMTP.
    
    Args:
        smtp_config: dict loaded from smtp_creds.json
        subject: subject text (used as fallback)
        message: body text (used as fallback if no template/devices)
        devices: list of device dicts for template formatting
        stats: dict with total/online/offline counts
        log_fn: optional function(level, message) for logging
    
    Returns:
        True if sent successfully, False otherwise
    """
    if not smtp_config or not smtp_config.get("enabled"):
        return False
    
    prefix = smtp_config.get("subject_prefix", "[Alert]")
    server_addr = smtp_config.get("server")
    port = smtp_config.get("port", 587)
    use_tls = smtp_config.get("use_tls", True)
    username = smtp_config.get("username")
    password = smtp_config.get("password")
    from_addr = smtp_config.get("from_addr")
    to_addr = smtp_config.get("to_addr")
    
    tmpl = load_template()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    is_offline = "OFFLINE" in subject.upper()
    is_online = "ONLINE" in subject.upper()
    is_wan = "WAN" in subject.upper()
    
    if is_offline:
        tmpl_subject = tmpl.get("offline_subject", subject)
    elif is_online:
        tmpl_subject = tmpl.get("online_subject", subject)
    elif is_wan:
        tmpl_subject = tmpl.get("wan_subject", subject)
    else:
        tmpl_subject = subject
    
    count = len(devices) if devices else 0
    try:
        full_subject = f"{prefix} {tmpl_subject.format(count=count)}"
    except:
        full_subject = f"{prefix} {subject}"
    
    if devices:
        device_list = format_device_list(devices, tmpl, is_wan=is_wan)
        s = stats or {}
        
        if is_offline:
            body_lines = tmpl.get("offline_body", [])
        elif is_online:
            body_lines = tmpl.get("online_body", [])
        elif is_wan:
            body_lines = tmpl.get("wan_body", ["{timestamp}", "", "{device_list}"])
        else:
            body_lines = ["{timestamp}", "", "{device_list}"]
        
        try:
            body = build_body(
                body_lines,
                timestamp=timestamp,
                count=count,
                device_list=device_list,
                total=s.get("total", "?"),
                online=s.get("online", "?"),
                offline=s.get("offline", "?"),
            )
        except Exception as e:
            body = f"Timestamp: {timestamp}\n\n{message}"
    else:
        body = f"Timestamp: {timestamp}\n\n{message}"
    
    print(f"[SMTP] Sending email alert...")
    print(f"[SMTP]   Server:  {server_addr}:{port} (TLS: {use_tls})")
    print(f"[SMTP]   From:    {from_addr}")
    print(f"[SMTP]   To:      {to_addr}")
    print(f"[SMTP]   Subject: {full_subject}")
    priority = smtp_config.get("priority", "normal").lower()
    if priority != "normal":
        print(f"[SMTP]   Priority: {priority.upper()}")
    
    if log_fn:
        log_fn("SMTP", f"Sending: {full_subject}")
    
    try:
        msg = MIMEMultipart()
        msg['Subject'] = full_subject
        msg['From'] = from_addr
        msg['To'] = to_addr
        
        # Add priority headers if configured
        # Priority: 1=High, 3=Normal, 5=Low
        priority = smtp_config.get("priority", "normal").lower()
        if priority == "high":
            msg['X-Priority'] = '1'
            msg['X-MSMail-Priority'] = 'High'
            msg['Importance'] = 'high'
        elif priority == "low":
            msg['X-Priority'] = '5'
            msg['X-MSMail-Priority'] = 'Low'
            msg['Importance'] = 'low'
        # Normal priority doesn't need headers
        
        msg.attach(MIMEText(body, 'plain'))
        
        with smtplib.SMTP(server_addr, port, timeout=30) as smtp:
            smtp.ehlo()
            if use_tls:
                smtp.starttls()
                smtp.ehlo()
            
            if username and password:
                print(f"[SMTP]   Authenticating as {username}...")
                smtp.login(username, password)
            
            smtp.send_message(msg)
        
        print(f"[SMTP] Email sent successfully")
        if log_fn:
            log_fn("SMTP", "Email sent successfully")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        print(f"[SMTP] Authentication failed: {e}")
        if log_fn:
            log_fn("ERROR", f"SMTP auth failed: {e}")
    except smtplib.SMTPException as e:
        print(f"[SMTP] SMTP error: {e}")
        if log_fn:
            log_fn("ERROR", f"SMTP error: {e}")
    except Exception as e:
        print(f"[SMTP] Failed: {e}")
        if log_fn:
            log_fn("ERROR", f"SMTP failed: {e}")
    
    return False


def test_connection(smtp_config):
    """
    Test SMTP connection, authentication, and send a test email.
    """
    if not smtp_config or not smtp_config.get("enabled"):
        print("[SMTP TEST] SMTP is disabled in config")
        return False
    
    server_addr = smtp_config.get("server")
    port = smtp_config.get("port", 587)
    use_tls = smtp_config.get("use_tls", True)
    username = smtp_config.get("username")
    password = smtp_config.get("password")
    from_addr = smtp_config.get("from_addr")
    to_addr = smtp_config.get("to_addr")
    prefix = smtp_config.get("subject_prefix", "[Alert]")
    
    print(f"[SMTP TEST] Server:  {server_addr}:{port} (TLS: {use_tls})")
    print(f"[SMTP TEST] From:    {from_addr}")
    print(f"[SMTP TEST] To:      {to_addr}")
    priority = smtp_config.get("priority", "normal").lower()
    if priority != "normal":
        print(f"[SMTP TEST] Priority: {priority.upper()}")
    print(f"[SMTP TEST] Connecting...")
    
    try:
        with smtplib.SMTP(server_addr, port, timeout=30) as smtp:
            smtp.ehlo()
            print(f"[SMTP TEST] EHLO OK")
            
            if use_tls:
                smtp.starttls()
                smtp.ehlo()
                print(f"[SMTP TEST] STARTTLS OK")
            
            if username and password:
                smtp.login(username, password)
                print(f"[SMTP TEST] Auth OK as {username}")
            
            tmpl = load_template()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            test_subject = f"{prefix} {tmpl.get('test_subject', 'SMTP Test')}"
            
            try:
                body = build_body(
                    tmpl.get("test_body", ["SMTP Test", "Timestamp: {timestamp}"]),
                    timestamp=timestamp,
                    server=server_addr,
                    port=port,
                    from_addr=from_addr,
                    to_addr=to_addr,
                )
            except:
                body = f"SMTP Test\nTimestamp: {timestamp}\nIf you received this, alerts are working."
            
            msg = MIMEMultipart()
            msg['Subject'] = test_subject
            msg['From'] = from_addr
            msg['To'] = to_addr
            
            # Add priority headers if configured
            priority = smtp_config.get("priority", "normal").lower()
            if priority == "high":
                msg['X-Priority'] = '1'
                msg['X-MSMail-Priority'] = 'High'
                msg['Importance'] = 'high'
            elif priority == "low":
                msg['X-Priority'] = '5'
                msg['X-MSMail-Priority'] = 'Low'
                msg['Importance'] = 'low'
            
            msg.attach(MIMEText(body, 'plain'))
            
            smtp.send_message(msg)
            print(f"[SMTP TEST] Test email SENT to {to_addr}")
            print(f"[SMTP TEST] PASSED")
            return True
            
    except smtplib.SMTPAuthenticationError as e:
        print(f"[SMTP TEST] Authentication FAILED: {e}")
    except smtplib.SMTPException as e:
        print(f"[SMTP TEST] SMTP error: {e}")
    except Exception as e:
        print(f"[SMTP TEST] Connection FAILED: {e}")
    
    return False
