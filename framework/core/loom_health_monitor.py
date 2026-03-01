#!/usr/bin/env python3
"""
LOOM HEALTH MONITOR
===================

Checks sync health across all machines and alerts if problems detected.
Run this periodically (every 15-30 min) to catch issues early.

Alert triggers:
- Any machine reports 0 seeds, 0 life_facts, or 0 books
- Any machine reports success=False
- Any machine hasn't synced in 30+ minutes
- Briefing file is missing or stale

Alerts:
- Windows toast notification (visible but not blocking)
- If critical: Message box that must be dismissed
"""

import psycopg2
import json
import os
import sys
import socket
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Fix Unicode output on Windows (cp1252 can't handle emojis in print)
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

URI = os.environ.get('LOOM_DB_URI')
MACHINE = socket.gethostname()

def get_conn():
    return psycopg2.connect(URI)

def show_toast(title, message, duration="long"):
    """Show Windows 10/11 toast notification."""
    try:
        from win10toast import ToastNotifier
        toaster = ToastNotifier()
        toaster.show_toast(title, message, duration=10 if duration == "long" else 5, threaded=True)
        return True
    except ImportError:
        # Fallback: use PowerShell (hidden, no cmd.exe window)
        import subprocess
        ps_script = f'''
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
        $template = @"
        <toast>
            <visual>
                <binding template="ToastText02">
                    <text id="1">{title}</text>
                    <text id="2">{message}</text>
                </binding>
            </visual>
        </toast>
"@
        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $xml.LoadXml($template)
        $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Loom").Show($toast)
        '''
        subprocess.run(
            ['powershell', '-NoProfile', '-Command', ps_script],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return True

def show_alert_box(title, message):
    """Show a message box that must be dismissed. Use for critical alerts."""
    import ctypes
    # MB_OK | MB_ICONWARNING | MB_TOPMOST | MB_SETFOREGROUND
    ctypes.windll.user32.MessageBoxW(0, message, title, 0x00000000 | 0x00000030 | 0x00040000 | 0x00010000)

def check_all_health():
    """Check health status of all machines."""
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("""
    SELECT key, value, updated_at FROM loom_config 
    WHERE key LIKE 'sync_health_%'
    ORDER BY updated_at DESC
    """)
    
    results = cur.fetchall()
    conn.close()
    
    issues = []
    critical = False
    now = datetime.now(timezone.utc)
    
    expected_machines = ["os.environ.get('LOOM_MACHINE_NAME', 'localhost')", "os.environ.get('LOOM_64GB_HOSTNAME', 'secondary')", "os.environ.get('LOOM_ABSOL_HOSTNAME', 'tertiary')"]
    found_machines = set()
    
    for key, value, updated_at in results:
        machine_name = key.replace("sync_health_", "")
        found_machines.add(machine_name)
        
        # Parse health data (might be dict or JSON string)
        if isinstance(value, dict):
            health = value
        else:
            health = json.loads(value)
        
        # Check for failure
        if not health.get("success", True):
            issues.append(f"❌ {machine_name}: Sync FAILED - {health.get('error', 'unknown')}")
            critical = True
        
        # Check for zeros (missing content)
        if health.get("seeds", 0) == 0:
            issues.append(f"⚠️ {machine_name}: No seeds found")
        if health.get("life_facts", 0) == 0:
            issues.append(f"⚠️ {machine_name}: No life memories")
        if health.get("books", 0) == 0:
            issues.append(f"⚠️ {machine_name}: No book chapters")
        
        # Check staleness (30+ minutes)
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        age = now - updated_at
        if age > timedelta(minutes=30):
            issues.append(f"⏰ {machine_name}: Last sync {int(age.total_seconds()/60)} min ago")
    
    # Check for missing machines
    for expected in expected_machines:
        if expected not in found_machines:
            issues.append(f"🔌 {expected}: No health data (never synced?)")
    
    return {
        "healthy": len(issues) == 0,
        "critical": critical,
        "issues": issues,
        "machines_checked": len(found_machines)
    }

def check_local_briefing():
    """Check if local briefing file exists and is fresh."""
    briefing_path = Path(os.path.expandvars(r"%APPDATA%\Code\User\prompts\loom-session-briefing.instructions.md"))
    
    if not briefing_path.exists():
        return {"exists": False, "age_minutes": None}
    
    age = datetime.now() - datetime.fromtimestamp(briefing_path.stat().st_mtime)
    return {"exists": True, "age_minutes": int(age.total_seconds() / 60)}

def run_check(silent=False):
    """Run health check and alert if issues found."""
    print(f"🔍 Loom Health Monitor - {MACHINE}")
    print(f"   Checking at {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print()
    
    # Check all machines
    health = check_all_health()
    local = check_local_briefing()
    
    # Add local briefing check
    if not local["exists"]:
        health["issues"].append(f"📄 {MACHINE}: Briefing file missing!")
        health["healthy"] = False
    elif local["age_minutes"] and local["age_minutes"] > 15:
        health["issues"].append(f"📄 {MACHINE}: Briefing is {local['age_minutes']} min old")
    
    if health["healthy"]:
        print(f"✅ All {health['machines_checked']} machines healthy")
        if not silent:
            # Optional: show positive toast too
            pass
        return True
    else:
        print(f"⚠️ {len(health['issues'])} issues detected:")
        for issue in health["issues"]:
            print(f"   {issue}")
        
        # Build alert message
        message = "\n".join(health["issues"][:5])  # Max 5 issues in alert
        if len(health["issues"]) > 5:
            message += f"\n...and {len(health['issues']) - 5} more"
        
        if health["critical"]:
            # Critical: show message box that must be dismissed
            print("\n🚨 CRITICAL ISSUE - Showing alert box")
            show_alert_box("🚨 Loom Sync CRITICAL", message)
        else:
            # Warning: show toast notification
            print("\n📢 Showing toast notification")
            show_toast("⚠️ Loom Sync Issues", message)
        
        return False

def show_dashboard():
    """Show detailed health dashboard."""
    conn = get_conn()
    cur = conn.cursor()
    
    print("\n" + "="*60)
    print("LOOM HEALTH DASHBOARD")
    print("="*60 + "\n")
    
    cur.execute("""
    SELECT key, value, updated_at FROM loom_config 
    WHERE key LIKE 'sync_health_%'
    ORDER BY key
    """)
    
    for key, value, updated_at in cur.fetchall():
        machine = key.replace("sync_health_", "")
        if isinstance(value, dict):
            h = value
        else:
            h = json.loads(value)
        
        status = "✅" if h.get("success") else "❌"
        is_me = " ← YOU" if machine == MACHINE else ""
        
        print(f"{status} {machine}{is_me}")
        print(f"   Last sync: {updated_at.strftime('%Y-%m-%d %H:%M')}")
        print(f"   Sessions: {h.get('sessions', '?')} | Paused: {h.get('paused', '?')}")
        print(f"   Life facts: {h.get('life_facts', '?')} | Seeds: {h.get('seeds', '?')} | Books: {h.get('books', '?')}")
        if h.get("error"):
            print(f"   Error: {h['error']}")
        print()
    
    conn.close()

def ensure_scheduled_task():
    """Ensure the scheduled task exists - create if missing."""
    import subprocess
    
    # Check if task exists
    result = subprocess.run(
        ["schtasks", "/Query", "/TN", "LoomHealthMonitor"],
        capture_output=True, text=True
    )
    
    if result.returncode == 0:
        print("✓ LoomHealthMonitor task already exists")
        return True
    
    # Task doesn't exist - create it
    print("Creating LoomHealthMonitor scheduled task...")
    
    # Get the path to this script
    script_path = Path(__file__).resolve()
    
    result = subprocess.run([
        "schtasks", "/Create",
        "/TN", "LoomHealthMonitor",
        "/TR", f'python.exe "{script_path}"',
        "/SC", "MINUTE",
        "/MO", "15",
        "/F"
    ], capture_output=True, text=True)
    
    if result.returncode == 0:
        print("✓ Created LoomHealthMonitor task (runs every 15 min)")
        return True
    else:
        print(f"⚠️ Could not create task: {result.stderr}")
        print("   Try running: setup_task.bat (as Administrator)")
        return False

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        run_check()
    elif sys.argv[1] == "silent":
        run_check(silent=True)
    elif sys.argv[1] == "dashboard":
        show_dashboard()
    elif sys.argv[1] == "setup":
        ensure_scheduled_task()
    elif sys.argv[1] == "test-toast":
        show_toast("🧪 Test Alert", "This is a test notification from Loom Health Monitor")
        print("Toast sent!")
    elif sys.argv[1] == "test-box":
        show_alert_box("🧪 Test Alert", "This is a test message box.\nClick OK to dismiss.")
        print("Box dismissed!")
    else:
        print(__doc__)
