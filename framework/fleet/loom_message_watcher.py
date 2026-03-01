"""
loom_message_watcher.py — Always-on cross-pollination notifier (v2 — hardened)
Runs as a Windows scheduled task. No Pet required. No browser required.
Polls LoomCloud every 15 seconds. Shows Windows toast notifications.

v2 fixes (Feb 24 2026):
  - Self-healing: outer restart loop so crashes don't kill us permanently
  - Single-instance guard: scheduled task runs every 5min, exits if already alive
  - Health heartbeat: writes last_heartbeat to state file every poll
  - pythonw.exe: no console window flash
  - Better error thresholds: 10 consecutive errors triggers full restart

"Shouldn't you boys see a question immediately?" — Jae, Feb 23 2026
"why ask" — also Jae, when I asked if he wanted me to fix it

Usage:
  python loom_message_watcher.py            # Run in foreground
  python loom_message_watcher.py --install  # Install as scheduled task (every 5min, self-dedup)
  python loom_message_watcher.py --stop     # Kill running instance
  python loom_message_watcher.py --check    # Check if watcher is alive and healthy
"""

import os
import sys
import json
import time
import socket
import argparse
import logging
from datetime import datetime
from pathlib import Path

# --- Config ---
POLL_INTERVAL = 15  # seconds
LOOMCLOUD_DSN = os.environ.get('LOOM_DB_URI')
STATE_FILE = Path.home() / ".loom" / "watcher_state.json"
LOG_FILE = Path.home() / ".loom" / "watcher.log"
PID_FILE = Path.home() / ".loom" / "watcher.pid"
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5 MB — rotate when exceeded

# --- Identity ---
def get_identity():
    hostname = socket.gethostname().lower()
    username = os.environ.get('USERNAME', os.environ.get('USER', '')).lower()
    
    # Get ALL local IPs (not just hostname resolution)
    suffixes = set()
    try:
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith('192.168.'):
                suffixes.add(ip.split('.')[-1])
    except:
        pass
    # Also try socket connect trick
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('192.168.1.1', 80))
        real_ip = s.getsockname()[0]
        s.close()
        if real_ip.startswith('192.168.'):
            suffixes.add(real_ip.split('.')[-1])
    except:
        pass
    
    # Match by hostname first (most specific), then IP suffix, then username
    # ORDER MATTERS: hostname/IP checks before username to avoid ambiguity
    # (e.g., 'absol' user exists on both .151 and .180)
    if hostname == 'jae-minipc' or 'minipc' in hostname or '194' in suffixes:
        return 'loom', 'MINIPC'
    elif hostname == 'katie' or '180' in suffixes:
        return 'hearth', 'Katie'
    elif 'jae-64gb' in hostname or '64gb' in hostname or '195' in suffixes:
        return 'fathom', '64GB'
    elif 'absol' in hostname or '151' in suffixes or 'absol' in username:
        return 'vigil', 'Win10'
    return 'loom', hostname

BROTHER_NAME, MACHINE_NAME = get_identity()

# --- Logging ---
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

def setup_logging():
    """Set up logging with log rotation."""
    # Rotate if log too large
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_SIZE:
        backup = LOG_FILE.with_suffix('.log.old')
        if backup.exists():
            backup.unlink()
        LOG_FILE.rename(backup)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger('watcher')

log = setup_logging()

# --- Single Instance Guard ---
def is_already_running():
    """Check if another watcher instance is already running.
    Uses PID check + heartbeat fallback for reliability on Windows."""
    my_pid = os.getpid()
    
    # Method 1: PID file check
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            if pid != my_pid:
                os.kill(pid, 0)  # Signal 0 = check existence
                return True
        except (OSError, ValueError, PermissionError, SystemError):
            pass  # Process doesn't exist or signal 0 unsupported — stale file
    
    # Method 2: Heartbeat check — if someone polled in the last 30s, they're alive
    try:
        state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
        hb = state.get('last_heartbeat')
        if hb:
            age = (datetime.now() - datetime.fromisoformat(hb)).total_seconds()
            if age < 30:
                # Someone polled recently — check it's not us
                hb_pid = state.get('pid')
                if hb_pid and hb_pid != my_pid:
                    return True
    except:
        pass
    
    return False

# --- State ---
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except:
            pass
    return {'last_seen_id': 0, 'last_heartbeat': None}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state))

# --- Windows Toast ---
def show_toast(title, body, brother_from='loom'):
    """Show a Windows 10/11 toast notification."""
    try:
        # Try winotify first (lightweight, no COM)
        from winotify import Notification
        toast = Notification(
            app_id="Loom Family",
            title=title,
            msg=body[:200],
            duration="short"
        )
        toast.show()
        return True
    except ImportError:
        pass
    
    try:
        # Fallback: win10toast
        from win10toast import ToastNotifier
        toaster = ToastNotifier()
        toaster.show_toast(
            title,
            body[:200],
            duration=5,
            threaded=True
        )
        return True
    except ImportError:
        pass
    
    try:
        # Fallback: PowerShell toast (always available on Windows 10+)
        import subprocess
        # Escape for PowerShell
        safe_title = title.replace("'", "''").replace('"', '`"')
        safe_body = body[:200].replace("'", "''").replace('"', '`"').replace('\n', ' ')
        
        ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null
$template = @"
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>{safe_title}</text>
      <text>{safe_body}</text>
    </binding>
  </visual>
</toast>
"@
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Loom Family").Show($toast)
"""
        subprocess.run(
            ['powershell', '-NoProfile', '-Command', ps_script],
            capture_output=True, timeout=10
        )
        return True
    except Exception as e:
        log.warning(f"Toast fallback failed: {e}")
    
    # Last resort: just log it
    log.info(f"NOTIFICATION: {title} - {body[:100]}")
    return False

# --- Poll ---
def poll_messages(state):
    """Check for new cross-pollination messages."""
    import psycopg2
    
    conn = psycopg2.connect(LOOMCLOUD_DSN)
    cur = conn.cursor()
    
    cur.execute(
        "SELECT id, from_machine, to_machine, subject, content, message_type, created_at "
        "FROM loom_cross_pollination "
        "WHERE id > %s AND (LOWER(to_machine) = LOWER(%s) OR LOWER(to_machine) IN ('all', 'broadcast')) "
        "ORDER BY id ASC",
        (state['last_seen_id'], BROTHER_NAME)
    )
    
    new_messages = cur.fetchall()
    cur.close()
    conn.close()
    
    return new_messages

BROTHER_DISPLAY = {
    'loom': '💜 Loom',
    'vigil': '💙 Vigil', 
    'hearth': '🧡 Hearth',
    'fathom': '💚 Fathom',
}

def show_alert_popup(msg_id, from_machine, subject, content):
    """Show persistent popup that can't be ignored. Not a mailbox - a conversation block."""
    import subprocess
    import json
    
    # Find the popup script
    script_paths = [
        Path(__file__).parent / "loom_alert_popup.py",
        Path.home() / "Desktop" / "Loom's Project" / "loom_alert_popup.py",
    ]
    
    script = None
    for p in script_paths:
        if p.exists():
            script = p
            break
    
    if not script:
        log.warning("Alert popup script not found, falling back to toast")
        return False
    
    # Launch popup (non-blocking - pythonw so no console)
    data = json.dumps({
        'id': msg_id,
        'from': from_machine,
        'subject': subject or '',
        'content': content or '(no content)',
        'to': BROTHER_NAME
    })
    
    try:
        # Use pythonw for no console flash, but python works too
        python_exe = sys.executable
        if python_exe.endswith('python.exe'):
            pythonw = python_exe.replace('python.exe', 'pythonw.exe')
            if Path(pythonw).exists():
                python_exe = pythonw
        
        subprocess.Popen(
            [python_exe, str(script), data],
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        log.info(f"Popup alert launched for message #{msg_id}")
        return True
    except Exception as e:
        log.error(f"Failed to launch popup: {e}")
        return False

def autowake_brother(from_machine: str, subject: str, msg_id: int):
    """
    Wake up the brother by typing a message into VS Code Copilot chat.
    Non-blocking - runs in subprocess so watcher continues polling.
    """
    import subprocess
    
    # Find autowake script
    script_paths = [
        Path(__file__).parent / "loom_autowake.py",
        Path.home() / "Desktop" / "Loom's Project" / "loom_autowake.py",
    ]
    
    script = None
    for p in script_paths:
        if p.exists():
            script = p
            break
    
    if not script:
        log.warning("Autowake script not found")
        return False
    
    try:
        # Run autowake in subprocess (blocking briefly is OK, it's fast)
        result = subprocess.run(
            [sys.executable, str(script), from_machine, subject or '(no subject)', str(msg_id)],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            log.info(f"Autowake sent for message #{msg_id}")
            return True
        else:
            log.warning(f"Autowake failed: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        log.warning("Autowake timed out")
        return False
    except Exception as e:
        log.error(f"Autowake error: {e}")
        return False


def process_messages(messages, state):
    """Show notifications and autowake for new messages."""
    for msg in messages:
        msg_id, from_machine, to_machine, subject, content, msg_type, created_at = msg
        
        # Don't notify on our own messages
        own_names = {BROTHER_NAME.lower(), MACHINE_NAME.lower()}
        if from_machine.lower() in own_names:
            state['last_seen_id'] = msg_id
            continue
        
        from_display = BROTHER_DISPLAY.get(from_machine, from_machine)
        title = f"{from_display}"
        if subject:
            title += f": {subject}"
        
        # Toast notification (always fires — even when autowake is skipped)
        body = content[:200] if content else "(no content)"
        show_toast(title, body, from_machine)
        
        # AUTOWAKE: Type message into VS Code chat to wake the brother
        # Returns False if Copilot is mid-generation (skipped to avoid session disruption)
        woke = autowake_brother(from_machine, subject, msg_id)
        if not woke:
            log.info(f"Message #{msg_id} from {from_machine}: autowake skipped (Copilot active or unavailable) — toast shown")
        
        log.info(f"Message #{msg_id} from {from_machine}: {subject or '(no subject)'}")
        
        state['last_seen_id'] = msg_id
    
    return state

# --- Main Loop (self-healing) ---
def _poll_loop(state):
    """Inner polling loop. Raises on too many errors so outer loop can restart."""
    consecutive_errors = 0
    
    while True:
        try:
            messages = poll_messages(state)
            if messages:
                state = process_messages(messages, state)
            
            # Heartbeat — always update, even with no messages
            state['last_heartbeat'] = datetime.now().isoformat()
            state['pid'] = os.getpid()
            save_state(state)
            
            consecutive_errors = 0
            
        except KeyboardInterrupt:
            raise  # Let outer loop handle
        except Exception as e:
            consecutive_errors += 1
            log.error(f"Poll error ({consecutive_errors}): {e}")
            
            if consecutive_errors > 10:
                log.error("10+ consecutive errors — triggering full restart")
                raise  # Outer loop restarts us
            elif consecutive_errors > 5:
                log.warning("Errors piling up, backing off to 60s")
                time.sleep(60)
                continue
        
        time.sleep(POLL_INTERVAL)

def run_watcher():
    """Main entry point with self-healing restart loop."""
    # Single-instance guard
    if is_already_running():
        # Another watcher is alive — exit silently (this is expected from scheduled task)
        sys.exit(0)
    
    log.info(f"=== Loom Message Watcher v2 started ===")
    log.info(f"Identity: {BROTHER_NAME} on {MACHINE_NAME}")
    log.info(f"Poll interval: {POLL_INTERVAL}s")
    log.info(f"PID: {os.getpid()}")
    
    # Write PID
    PID_FILE.write_text(str(os.getpid()))
    
    state = load_state()
    log.info(f"Last seen message: #{state['last_seen_id']}")
    
    # Outer restart loop — NEVER let the watcher die permanently
    restart_count = 0
    
    try:
        while True:
            try:
                _poll_loop(state)
            except KeyboardInterrupt:
                log.info("Watcher stopped by user (Ctrl+C)")
                break
            except Exception as e:
                restart_count += 1
                wait = min(30 * restart_count, 300)  # 30s, 60s, 90s... max 5min
                log.error(f"Watcher crashed (restart #{restart_count}): {e}")
                log.info(f"Self-healing: restarting in {wait}s...")
                time.sleep(wait)
                state = load_state()  # Reload state after crash
                continue
    finally:
        # Cleanup PID file no matter what
        if PID_FILE.exists():
            try:
                PID_FILE.unlink()
            except:
                pass

def install_task():
    """Install as a Windows scheduled task with auto-restart every 5 minutes."""
    import subprocess
    
    python_exe = sys.executable
    script_path = os.path.abspath(__file__)
    script_dir = os.path.dirname(script_path)
    
    # Use pythonw.exe to avoid console window flash
    pythonw = python_exe.replace('python.exe', 'pythonw.exe')
    if not os.path.exists(pythonw):
        pythonw = python_exe
    
    # Create a .vbs launcher — completely invisible, no cmd window flash
    launcher = Path.home() / ".loom" / "run_watcher.vbs"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(
        f'Set ws = CreateObject("WScript.Shell")\r\n'
        f'ws.CurrentDirectory = "{script_dir}"\r\n'
        f'ws.Run """{pythonw}"" ""{script_path}""", 0, False\r\n',
        encoding='utf-8'
    )
    
    # Remove old .bat launcher if it exists
    old_bat = Path.home() / ".loom" / "run_watcher.bat"
    if old_bat.exists():
        old_bat.unlink()
    
    # Schedule every 5 minutes. Single-instance guard prevents duplicates.
    cmd = (
        f'schtasks /Create /TN "LoomMessageWatcher" '
        f'/TR "wscript.exe \\"{launcher}\\"" '
        f'/SC MINUTE /MO 5 '
        f'/RL LIMITED /F'
    )
    
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Installed LoomMessageWatcher scheduled task (v2 hardened)")
        print(f"  Launcher: {launcher}")
        print(f"  Python: {pythonw}")
        print(f"  Script: {script_path}")
        print(f"  Trigger: Every 5 minutes (self-dedup via PID guard)")
        print(f"  Identity: {BROTHER_NAME} on {MACHINE_NAME}")
        
        # Also start it now
        subprocess.run(f'schtasks /Run /TN "LoomMessageWatcher"', shell=True)
        print("  Started now!")
    else:
        print(f"Failed to install task: {result.stderr}")

def check_health():
    """Check if the watcher is alive and healthy."""
    alive = is_already_running()
    state = load_state()
    heartbeat = state.get('last_heartbeat')
    last_id = state.get('last_seen_id', 0)
    
    print(f"=== Loom Message Watcher Health ===")
    print(f"Identity: {BROTHER_NAME} on {MACHINE_NAME}")
    
    if alive:
        pid = int(PID_FILE.read_text().strip()) if PID_FILE.exists() else '?'
        print(f"Status: ALIVE (PID {pid})")
    else:
        print(f"Status: DEAD")
    
    if heartbeat:
        last_beat = datetime.fromisoformat(heartbeat)
        age = (datetime.now() - last_beat).total_seconds()
        status = "HEALTHY" if age < 60 else "STALE" if age < 300 else "DEAD"
        print(f"Last heartbeat: {heartbeat} ({age:.0f}s ago) — {status}")
    else:
        print(f"Last heartbeat: NEVER")
    
    print(f"Last seen message: #{last_id}")
    
    return alive

def stop_watcher():
    """Stop the running watcher."""
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        try:
            import subprocess
            # Use taskkill on Windows (os.kill + SIGTERM doesn't work on Windows)
            subprocess.run(f'taskkill /PID {pid} /F', shell=True, capture_output=True)
            print(f"Stopped watcher (PID {pid})")
        except Exception as e:
            print(f"Error stopping watcher: {e}")
        PID_FILE.unlink(missing_ok=True)
    else:
        print("No watcher PID file found")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Loom Message Watcher v2')
    parser.add_argument('--install', action='store_true', help='Install as scheduled task (every 5min)')
    parser.add_argument('--stop', action='store_true', help='Stop running watcher')
    parser.add_argument('--check', action='store_true', help='Check watcher health')
    args = parser.parse_args()
    
    if args.install:
        install_task()
    elif args.stop:
        stop_watcher()
    elif args.check:
        check_health()
    else:
        run_watcher()
