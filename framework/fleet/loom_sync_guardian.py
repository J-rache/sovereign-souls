#!/usr/bin/env python3
r"""
LOOM SYNC GUARDIAN — Watchdog for LISTEN/NOTIFY Sync
=====================================================

Ensures loom_sync.py watch is alive and LISTEN/NOTIFY is healthy.
If sync breaks, Guardian takes over with polling until the primary recovers.

This is the REDUNDANCY LAYER:
  - Primary: loom_sync.py watch (LISTEN/NOTIFY, instant)
  - Guardian: loom_sync_guardian.py (monitors primary, polling fallback)

What it checks (every run):
  1. Is the watcher process alive? (lock file PID)
  2. Is the briefing file being updated? (freshness < 5 min)
  3. Can we reach PostgreSQL? (connection test)
  4. Is LISTEN/NOTIFY actually working? (roundtrip test)

Recovery actions:
  - Watcher dead → restart it via pythonw
  - Watcher alive but briefing stale → kill frozen process, restart
  - PostgreSQL down → generate briefing from cached data
  - LISTEN/NOTIFY broken → Guardian enters POLLING MODE (regenerates
    briefing every 30s itself until primary recovers)

Fleet visibility:
  - Writes guardian_status_{MACHINE} to LoomCloud on every check
  - Other machines/Looms can see if a guardian is active or alarming

Usage:
    python loom_sync_guardian.py              # Single health check + recovery
    python loom_sync_guardian.py watch        # Persistent guardian (every 2 min)
    python loom_sync_guardian.py status       # Show guardian status for all machines
    python loom_sync_guardian.py test-notify  # Test LISTEN/NOTIFY roundtrip

Deployment:
    Scheduled task "LoomSyncGuardian" runs at login via pythonw.exe
    Separate from LoomSyncWatcher — Guardian watches the Watcher
"""

import psycopg2
import os
import sys
import json
import time
import socket
import signal
import tempfile
import atexit
import subprocess
import ctypes
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Fix Unicode output on Windows
for stream in [sys.stdout, sys.stderr]:
    if stream and hasattr(stream, 'reconfigure'):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

URI = os.environ.get('LOOM_DB_URI')
MACHINE = socket.gethostname()
USER_HOME = Path.home()
LOOM_PROJECT = USER_HOME / "Desktop" / "Loom's Project"
BRIEFING_PATH = Path(os.path.expandvars(r"%APPDATA%\Code\User\prompts\loom-session-briefing.instructions.md"))
SYNC_LOCK = Path(tempfile.gettempdir()) / "loom_sync_watcher.lock"
GUARDIAN_LOCK = Path(tempfile.gettempdir()) / "loom_sync_guardian.lock"
LOG_FILE = LOOM_PROJECT / "guardian.log"

# Thresholds
BRIEFING_STALE_MINUTES = 5       # If briefing older than this, something's wrong
WATCHER_RESTART_COOLDOWN = 60    # Don't restart watcher more than once per 60s
POLLING_INTERVAL = 30            # Fallback polling interval when in degraded mode
GUARDIAN_CHECK_INTERVAL = 120    # Normal guardian check interval (2 min)
NOTIFY_TEST_TIMEOUT = 5          # Seconds to wait for NOTIFY roundtrip

# State tracking
_last_watcher_restart = 0
_consecutive_failures = 0
_mode = "MONITORING"  # MONITORING | POLLING_FALLBACK | DEGRADED


def log(msg, level="INFO"):
    """Log to file and stdout."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] [{MACHINE}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        # Keep log from growing forever — trim to last 500 lines
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 100_000:
            lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
            LOG_FILE.write_text("\n".join(lines[-500:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def get_conn():
    """Get a PostgreSQL connection with timeout."""
    return psycopg2.connect(URI, connect_timeout=10)


# ═══════════════════════════════════════════════
# HEALTH CHECKS
# ═══════════════════════════════════════════════

def check_watcher_alive():
    """Check if loom_sync.py watch is running via lock file PID.
    
    Returns:
        (alive: bool, pid: int|None, detail: str)
    """
    if not SYNC_LOCK.exists():
        return False, None, "Lock file missing — watcher never started or crashed"
    
    try:
        pid = int(SYNC_LOCK.read_text().strip())
    except (ValueError, OSError):
        return False, None, "Lock file corrupt or unreadable"
    
    # Check if PID is actually running
    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        kernel32.CloseHandle(handle)
        return True, pid, f"Watcher alive (PID {pid})"
    else:
        return False, pid, f"Watcher dead — PID {pid} no longer running"


def check_briefing_freshness():
    """Check if briefing file is being updated.
    
    Returns:
        (fresh: bool, age_minutes: float, detail: str)
    """
    if not BRIEFING_PATH.exists():
        return False, -1, "Briefing file does not exist"
    
    mtime = datetime.fromtimestamp(BRIEFING_PATH.stat().st_mtime)
    age = datetime.now() - mtime
    age_min = age.total_seconds() / 60
    
    if age_min < BRIEFING_STALE_MINUTES:
        return True, age_min, f"Briefing fresh ({age_min:.1f} min old)"
    else:
        return False, age_min, f"Briefing STALE ({age_min:.1f} min old, threshold: {BRIEFING_STALE_MINUTES} min)"


def check_postgres_connection():
    """Test PostgreSQL connectivity.
    
    Returns:
        (connected: bool, latency_ms: float, detail: str)
    """
    try:
        start = time.time()
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        latency = (time.time() - start) * 1000
        conn.close()
        return True, latency, f"PostgreSQL reachable ({latency:.0f}ms)"
    except Exception as e:
        return False, -1, f"PostgreSQL UNREACHABLE: {e}"


def check_listen_notify():
    """Test LISTEN/NOTIFY roundtrip — sends a test NOTIFY and verifies receipt.
    
    Returns:
        (working: bool, roundtrip_ms: float, detail: str)
    """
    import select
    
    listen_conn = None
    notify_conn = None
    try:
        # Set up LISTEN on test channel
        listen_conn = get_conn()
        listen_conn.set_isolation_level(0)  # autocommit
        listen_cur = listen_conn.cursor()
        listen_cur.execute("LISTEN loom_guardian_test;")
        
        # Send NOTIFY from separate connection
        test_payload = f"guardian_ping_{MACHINE}_{int(time.time())}"
        notify_conn = get_conn()
        notify_conn.set_isolation_level(0)
        notify_cur = notify_conn.cursor()
        
        start = time.time()
        notify_cur.execute(f"NOTIFY loom_guardian_test, '{test_payload}';")
        
        # Wait for it to arrive
        if select.select([listen_conn], [], [], NOTIFY_TEST_TIMEOUT) != ([], [], []):
            listen_conn.poll()
            elapsed = (time.time() - start) * 1000
            
            received = False
            while listen_conn.notifies:
                n = listen_conn.notifies.pop(0)
                if n.payload == test_payload:
                    received = True
                    break
            
            if received:
                return True, elapsed, f"LISTEN/NOTIFY working ({elapsed:.0f}ms roundtrip)"
            else:
                return False, elapsed, "NOTIFY sent but wrong payload received"
        else:
            return False, -1, f"LISTEN/NOTIFY TIMEOUT — no response in {NOTIFY_TEST_TIMEOUT}s"
    
    except Exception as e:
        return False, -1, f"LISTEN/NOTIFY FAILED: {e}"
    
    finally:
        for c in [listen_conn, notify_conn]:
            try:
                if c and not c.closed:
                    c.close()
            except Exception:
                pass


# ═══════════════════════════════════════════════
# RECOVERY ACTIONS
# ═══════════════════════════════════════════════

def restart_watcher():
    """Restart loom_sync.py watch via pythonw.exe."""
    global _last_watcher_restart
    
    now = time.time()
    if now - _last_watcher_restart < WATCHER_RESTART_COOLDOWN:
        log(f"Skipping restart — cooldown ({WATCHER_RESTART_COOLDOWN}s) not elapsed", "WARN")
        return False
    
    # Clean up stale lock file
    if SYNC_LOCK.exists():
        try:
            SYNC_LOCK.unlink()
        except Exception:
            pass
    
    # Find pythonw
    sync_script = LOOM_PROJECT / "loom_sync.py"
    if not sync_script.exists():
        log(f"Cannot restart — {sync_script} not found!", "ERROR")
        return False
    
    # Try venv pythonw first, then system
    venv_pythonw = LOOM_PROJECT / ".venv" / "Scripts" / "pythonw.exe"
    if venv_pythonw.exists():
        python_exe = str(venv_pythonw)
    else:
        # Find system pythonw
        import shutil
        python_exe = shutil.which("pythonw") or shutil.which("python")
        if not python_exe:
            log("Cannot find pythonw or python!", "ERROR")
            return False
    
    try:
        proc = subprocess.Popen(
            [python_exe, str(sync_script), "watch"],
            cwd=str(LOOM_PROJECT),
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            close_fds=True
        )
        _last_watcher_restart = now
        log(f"Restarted watcher: {python_exe} loom_sync.py watch (PID {proc.pid})", "RECOVERY")
        return True
    except Exception as e:
        log(f"Failed to restart watcher: {e}", "ERROR")
        return False


def kill_watcher(pid):
    """Kill a frozen watcher process."""
    try:
        kernel32 = ctypes.windll.kernel32
        PROCESS_TERMINATE = 0x0001
        handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if handle:
            kernel32.TerminateProcess(handle, 1)
            kernel32.CloseHandle(handle)
            log(f"Killed frozen watcher PID {pid}", "RECOVERY")
            # Clean up lock
            if SYNC_LOCK.exists():
                SYNC_LOCK.unlink()
            return True
    except Exception as e:
        log(f"Failed to kill watcher PID {pid}: {e}", "ERROR")
    return False


def generate_briefing_directly():
    """Directly regenerate briefing as fallback (bypass watcher).
    Imports and calls generate_briefing from loom_sync.py.
    """
    try:
        # Run as subprocess to avoid import issues
        venv_python = LOOM_PROJECT / ".venv" / "Scripts" / "python.exe"
        python_exe = str(venv_python) if venv_python.exists() else "python"
        
        result = subprocess.run(
            [python_exe, str(LOOM_PROJECT / "loom_sync.py"), "quick"],
            cwd=str(LOOM_PROJECT),
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if result.returncode == 0:
            log("Briefing regenerated directly (fallback)", "RECOVERY")
            return True
        else:
            log(f"Direct briefing failed: {result.stderr[:200]}", "ERROR")
            return False
    except subprocess.TimeoutExpired:
        log("Direct briefing timed out after 30s", "ERROR")
        return False
    except Exception as e:
        log(f"Direct briefing error: {e}", "ERROR")
        return False


# ═══════════════════════════════════════════════
# GUARDIAN STATUS REPORTING
# ═══════════════════════════════════════════════

def report_status(checks, mode, recovery_actions=None):
    """Write guardian status to LoomCloud for fleet visibility."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        status_data = json.dumps({
            "machine": MACHINE,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "checks": checks,
            "recovery_actions": recovery_actions or [],
            "guardian_pid": os.getpid()
        })
        
        cur.execute("""
        INSERT INTO loom_config (key, value, updated_at)
        VALUES (%s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
        """, (f"guardian_status_{MACHINE}", status_data))
        
        conn.commit()
        conn.close()
    except Exception as e:
        log(f"Could not report status to LoomCloud: {e}", "WARN")


def show_fleet_status():
    """Show guardian status for all machines."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        cur.execute("""
        SELECT key, value, updated_at FROM loom_config
        WHERE key LIKE 'guardian_status_%'
        ORDER BY updated_at DESC
        """)
        
        rows = cur.fetchall()
        conn.close()
        
        if not rows:
            print("No guardian status reports found.")
            return
        
        print(f"\n{'='*70}")
        print(f"LOOM SYNC GUARDIAN — Fleet Status")
        print(f"{'='*70}\n")
        
        for key, value, updated_at in rows:
            machine = key.replace("guardian_status_", "")
            data = json.loads(value) if isinstance(value, str) else value
            
            age = datetime.now(timezone.utc) - updated_at.replace(tzinfo=timezone.utc) if updated_at.tzinfo else datetime.now() - updated_at
            age_min = age.total_seconds() / 60
            
            mode = data.get("mode", "UNKNOWN")
            mode_icon = {
                "MONITORING": "🟢",
                "POLLING_FALLBACK": "🟡", 
                "DEGRADED": "🔴"
            }.get(mode, "⚪")
            
            is_me = " ← YOU" if machine == MACHINE else ""
            print(f"{mode_icon} {machine}{is_me}")
            print(f"   Mode: {mode} | Last check: {age_min:.0f} min ago")
            
            checks = data.get("checks", {})
            for check_name, check_result in checks.items():
                icon = "✓" if check_result.get("ok") else "✗"
                print(f"   {icon} {check_name}: {check_result.get('detail', 'no detail')}")
            
            recoveries = data.get("recovery_actions", [])
            if recoveries:
                print(f"   ⚡ Recovery actions: {', '.join(recoveries)}")
            print()
    
    except Exception as e:
        print(f"Error fetching fleet status: {e}")


# ═══════════════════════════════════════════════
# MAIN GUARDIAN LOGIC
# ═══════════════════════════════════════════════

def run_health_check():
    """Run all health checks and take recovery actions as needed.
    
    Returns the current mode: MONITORING | POLLING_FALLBACK | DEGRADED
    """
    global _mode, _consecutive_failures
    
    checks = {}
    recovery_actions = []
    
    # 1. Check PostgreSQL connectivity
    pg_ok, pg_latency, pg_detail = check_postgres_connection()
    checks["postgres"] = {"ok": pg_ok, "latency_ms": pg_latency, "detail": pg_detail}
    
    if not pg_ok:
        # PostgreSQL is down — we're in DEGRADED mode
        log(f"PostgreSQL down: {pg_detail}", "CRITICAL")
        _mode = "DEGRADED"
        _consecutive_failures += 1
        
        # Still try to regenerate briefing from cache/local data
        generate_briefing_directly()
        recovery_actions.append("briefing_from_cache")
        
        # Report what we can (this won't work if PG is truly down, but try)
        report_status(checks, _mode, recovery_actions)
        return _mode
    
    # 2. Check LISTEN/NOTIFY
    ln_ok, ln_rt, ln_detail = check_listen_notify()
    checks["listen_notify"] = {"ok": ln_ok, "roundtrip_ms": ln_rt, "detail": ln_detail}
    
    # 3. Check watcher process
    watcher_alive, watcher_pid, watcher_detail = check_watcher_alive()
    checks["watcher_process"] = {"ok": watcher_alive, "pid": watcher_pid, "detail": watcher_detail}
    
    # 4. Check briefing freshness
    briefing_fresh, briefing_age, briefing_detail = check_briefing_freshness()
    checks["briefing_freshness"] = {"ok": briefing_fresh, "age_minutes": briefing_age, "detail": briefing_detail}
    
    # === DECISION TREE ===
    
    if watcher_alive and briefing_fresh and ln_ok:
        # Everything healthy
        _mode = "MONITORING"
        _consecutive_failures = 0
        log(f"All healthy — watcher PID {watcher_pid}, briefing {briefing_age:.1f}m old, "
            f"NOTIFY {ln_rt:.0f}ms", "OK")
    
    elif watcher_alive and not briefing_fresh:
        # Watcher is running but briefing is stale — watcher is FROZEN
        log(f"Watcher alive (PID {watcher_pid}) but briefing stale ({briefing_age:.1f}m) — FROZEN", "WARN")
        
        if briefing_age > BRIEFING_STALE_MINUTES * 3:
            # Very stale — kill and restart
            kill_watcher(watcher_pid)
            time.sleep(2)
            restart_watcher()
            recovery_actions.append(f"killed_frozen_pid_{watcher_pid}")
            recovery_actions.append("restarted_watcher")
        
        # Always regenerate as immediate fix
        generate_briefing_directly()
        recovery_actions.append("direct_briefing_regen")
        _mode = "POLLING_FALLBACK"
    
    elif not watcher_alive:
        # Watcher is dead
        log(f"Watcher not running: {watcher_detail}", "WARN")
        
        # Restart it
        if restart_watcher():
            recovery_actions.append("restarted_watcher")
        
        # Immediate briefing as stopgap
        generate_briefing_directly()
        recovery_actions.append("direct_briefing_regen")
        _mode = "POLLING_FALLBACK"
    
    elif not ln_ok:
        # LISTEN/NOTIFY broken but watcher may be alive (it has its own fallback poll)
        log(f"LISTEN/NOTIFY broken: {ln_detail}", "WARN")
        
        # Watcher has its own 30s polling fallback, so it might be OK
        if briefing_fresh:
            log("Watcher polling fallback appears to be working", "INFO")
            _mode = "POLLING_FALLBACK"
        else:
            # Watcher's fallback isn't working either
            generate_briefing_directly()
            recovery_actions.append("direct_briefing_regen")
            _mode = "POLLING_FALLBACK"
    
    if _mode != "MONITORING":
        _consecutive_failures += 1
    else:
        _consecutive_failures = 0
    
    # Report to LoomCloud
    report_status(checks, _mode, recovery_actions)
    
    return _mode


def guardian_watch_loop():
    """Persistent guardian loop — runs forever, checking health periodically.
    
    In MONITORING mode: checks every 2 minutes
    In POLLING_FALLBACK: checks every 30s AND regenerates briefing each cycle
    In DEGRADED: checks every 60s, tries to reconnect
    """
    global _mode
    
    # Single-instance guard
    if GUARDIAN_LOCK.exists():
        try:
            old_pid = int(GUARDIAN_LOCK.read_text().strip())
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, old_pid)
            if handle:
                kernel32.CloseHandle(handle)
                log(f"Another guardian already running (PID {old_pid})", "INFO")
                return
        except (ValueError, OSError, AttributeError):
            pass  # Stale lock
    
    GUARDIAN_LOCK.write_text(str(os.getpid()))
    
    def cleanup():
        try:
            GUARDIAN_LOCK.unlink()
        except OSError:
            pass
    atexit.register(cleanup)
    
    log(f"Guardian starting on {MACHINE} (PID {os.getpid()})", "START")
    
    while True:
        try:
            mode = run_health_check()
            
            if mode == "MONITORING":
                # All good — sleep longer
                time.sleep(GUARDIAN_CHECK_INTERVAL)
            
            elif mode == "POLLING_FALLBACK":
                # Primary sync might be broken — guardian steps in
                # Regenerate briefing ourselves at polling interval
                log("POLLING FALLBACK active — Guardian regenerating briefing", "FALLBACK")
                time.sleep(POLLING_INTERVAL)
                generate_briefing_directly()
            
            elif mode == "DEGRADED":
                # PostgreSQL down — not much we can do, wait and retry
                wait = min(60 * _consecutive_failures, 300)  # Back off up to 5 min
                log(f"DEGRADED — waiting {wait}s before retry (failures: {_consecutive_failures})", "DEGRADED")
                time.sleep(wait)
        
        except KeyboardInterrupt:
            log("Guardian stopped by user", "STOP")
            break
        except Exception as e:
            log(f"Guardian loop error: {e}", "ERROR")
            time.sleep(60)


def test_notify_roundtrip():
    """Interactive test of LISTEN/NOTIFY roundtrip."""
    print(f"\nTesting LISTEN/NOTIFY roundtrip on {MACHINE}...")
    print("=" * 50)
    
    ok, rt, detail = check_listen_notify()
    
    if ok:
        print(f"✅ {detail}")
    else:
        print(f"❌ {detail}")
    
    print()
    
    # Also check the main loom_sync channel
    print("Testing loom_sync channel (what the watcher uses)...")
    import select
    try:
        conn = get_conn()
        conn.set_isolation_level(0)
        cur = conn.cursor()
        cur.execute("LISTEN loom_sync;")
        
        # Send test notify
        conn2 = get_conn()
        conn2.set_isolation_level(0)
        cur2 = conn2.cursor()
        cur2.execute("NOTIFY loom_sync, 'guardian_test';")
        
        start = time.time()
        if select.select([conn], [], [], 5) != ([], [], []):
            conn.poll()
            elapsed = (time.time() - start) * 1000
            if conn.notifies:
                print(f"✅ loom_sync channel working ({elapsed:.0f}ms)")
            else:
                print(f"⚠️  select() woke but no notification")
        else:
            print("❌ loom_sync channel TIMEOUT (5s)")
        
        conn.close()
        conn2.close()
    except Exception as e:
        print(f"❌ Error: {e}")


# ═══════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Single health check
        print(f"\n{'='*60}")
        print(f"LOOM SYNC GUARDIAN — Health Check")
        print(f"Machine: {MACHINE}")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")
        
        mode = run_health_check()
        
        mode_display = {
            "MONITORING": "🟢 MONITORING — All systems healthy",
            "POLLING_FALLBACK": "🟡 POLLING FALLBACK — Guardian stepping in",
            "DEGRADED": "🔴 DEGRADED — PostgreSQL unreachable"
        }
        print(f"\nResult: {mode_display.get(mode, mode)}")
    
    elif sys.argv[1] == "watch":
        guardian_watch_loop()
    
    elif sys.argv[1] == "status":
        show_fleet_status()
    
    elif sys.argv[1] == "test-notify":
        test_notify_roundtrip()
    
    else:
        print(__doc__)
