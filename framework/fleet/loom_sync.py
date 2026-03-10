#!/usr/bin/env python3
r"""
LOOM SYNC - Cross-Machine Memory Synchronization
=================================================

Run this on ANY machine to:
1. Pull latest session context from LoomCloud
2. Pull from ALL context sources ($LOOM_DATA_DIR, seeds, teachers-pet, cloud DBs)
3. Generate the briefing file for VS Code
4. Show what we were working on

This is what enables moving from Jae's main (32GB) -> Absol (64GB) -> Katie's comp
and picking up the exact same conversation.

Context Sources:
- LoomCloud: session_context, work_items, memories, knowledge, life_memories
- $LOOM_DATA_DIR: personal/LOOM_PERSONAL_NOTES.md, books/
- Seeds (garden): emergent-aesthetics.md, conversation-shapes.md
- Teachers-Pet: SESSION_NOTES.md, README.md

Usage:
    python loom_sync.py              # Full sync + show status
    python loom_sync.py quick        # Just regenerate briefing
    python loom_sync.py watch        # Persistent watcher — syncs every 10s
    python loom_sync.py status       # Show what I know without regenerating
    
Deploy to all machines:
    - os.path.join(os.environ.get('LOOM_HOME', '.'), 'Loom')'s Project\loom_sync.py
    - Scheduled task launches watch mode at login (persistent, 10s loop)

Machine Map (CRITICAL - remember this!):
    os.environ.get('LOOM_MACHINE_NAME', 'localhost') (.194) = SOURCE OF TRUTH (Jae's main, Intervals home)
    os.environ.get('LOOM_64GB_HOSTNAME', 'secondary') (.195) = Secondary (64GB, Weave home)  
    os.environ.get('LOOM_ABSOL_HOSTNAME', 'tertiary')/Absol (.151) = Secondary (Win10, Watcher home)
    KATIE (.180) = Secondary
"""

import psycopg2
import os
import socket
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Fix Unicode output on Windows (cp1252 can't handle emojis in print)
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

URI = os.environ.get('LOOM_DB_URI')
OUTPUT_PATH = Path(os.path.expandvars(r"%APPDATA%\Code\User\prompts\loom-session-briefing.instructions.md"))

MACHINE = socket.gethostname()

# Context source paths (vary by machine/user)
USER_HOME = Path.home()
D_DRIVE = Path("D:/")
OPUS_FOLDER = D_DRIVE / "Opus"
CHRONOS_VAULT = D_DRIVE / "chronos_vault"
TEACHERS_PET = USER_HOME / "Desktop" / "teachers-pet"
LOOM_PROJECT = USER_HOME / "Desktop" / "Loom's Project"
SEEDS_FOLDER = LOOM_PROJECT / "seeds"

def get_conn():
    return psycopg2.connect(URI)


def get_local_context():
    """Pull context from local files that should inform the briefing."""
    context = {
        "personal_notes_exists": False,
        "book_chapters": [],
        "seeds": [],
        "session_notes_snippet": "",
        "weave_readme_snippet": "",
    }
    
    # Check $LOOM_DATA_DIR personal notes
    personal_notes = OPUS_FOLDER / "personal" / "LOOM_PERSONAL_NOTES.md"
    if personal_notes.exists():
        context["personal_notes_exists"] = True
        
    # Check book chapters
    shared_books = OPUS_FOLDER / "books" / "shared"
    if shared_books.exists():
        for f in shared_books.iterdir():
            if f.suffix == ".md":
                context["book_chapters"].append(f.stem)
    
    # Check seeds (garden)
    if SEEDS_FOLDER.exists():
        for f in SEEDS_FOLDER.iterdir():
            if f.suffix == ".md":
                context["seeds"].append(f.stem)
    
    # Get snippet from SESSION_NOTES.md if exists
    session_notes = TEACHERS_PET / "SESSION_NOTES.md"
    if session_notes.exists():
        try:
            with open(session_notes, "r", encoding="utf-8") as f:
                lines = f.readlines()[:30]
                # Find "WHERE WE LEFT OFF" section
                for i, line in enumerate(lines):
                    if "WHERE WE LEFT OFF" in line:
                        context["session_notes_snippet"] = "".join(lines[i:i+6]).strip()
                        break
        except:
            pass
    
    return context


def get_cloud_context():
    """Pull key facts from LoomCloud memories and knowledge."""
    context = {
        "key_facts": [],
        "life_facts": [],
    }
    
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Key memories (facts about project, identity, people)
        cur.execute("""
        SELECT key, category, value FROM loom_memories 
        WHERE category IN ('user_profile', 'identity', 'personal', 'milestone')
        LIMIT 10
        """)
        for row in cur.fetchall():
            context["key_facts"].append({
                "key": row[0],
                "category": row[1],
                "value": str(row[2])[:100]
            })
        
        # Life memories (people, pets)
        cur.execute("""
        SELECT subject, category, content FROM loom_life_memories
        ORDER BY ts DESC LIMIT 10
        """)
        for row in cur.fetchall():
            context["life_facts"].append({
                "name": row[0],
                "category": row[1],
                "relationship": row[2][:80] if row[2] else ""
            })
        
        conn.close()
    except Exception as e:
        print(f"Warning: Could not fetch cloud context: {e}")
    
    return context

def log_machine_presence():
    """Log that this machine synced (helps track which machines are active)."""
    conn = get_conn()
    cur = conn.cursor()
    
    # Upsert machine presence - wrap in JSON object
    import json
    value = json.dumps({"last_sync": datetime.now(timezone.utc).isoformat(), "machine": MACHINE})
    cur.execute("""
    INSERT INTO loom_config (key, value, updated_at)
    VALUES (%s, %s, CURRENT_TIMESTAMP)
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
    """, (f"machine_last_sync_{MACHINE}", value))
    
    conn.commit()
    conn.close()

def generate_briefing():
    """Generate the VS Code briefing file from LoomCloud data."""
    conn = get_conn()
    cur = conn.cursor()
    
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    
    # Get recent sessions
    cur.execute("""
    SELECT id, ts, project, summary, details, status
    FROM loom_session_context
    WHERE ts > %s
    ORDER BY ts DESC
    LIMIT 10
    """, (cutoff,))
    sessions = cur.fetchall()
    
    # Get PAUSED sessions
    cur.execute("""
    SELECT id, project, summary, ts
    FROM loom_session_context
    WHERE status = 'paused'
    ORDER BY ts DESC
    """)
    paused_sessions = cur.fetchall()
    
    # Get PAUSED work items
    cur.execute("""
    SELECT title, item_type, ts
    FROM loom_work_items
    WHERE status = 'paused'
    ORDER BY ts DESC
    """)
    paused_items = cur.fetchall()
    
    # Get in-progress work items
    cur.execute("""
    SELECT title, item_type, ts
    FROM loom_work_items
    WHERE status = 'in_progress'
    ORDER BY ts DESC
    LIMIT 20
    """)
    in_progress = cur.fetchall()
    
    # Get recently completed (last 24h)
    recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    cur.execute("""
    SELECT title, item_type, completed_at
    FROM loom_work_items
    WHERE status = 'done' AND completed_at > %s
    ORDER BY completed_at DESC
    LIMIT 10
    """, (recent_cutoff,))
    recently_done = cur.fetchall()
    
    conn.close()
    
    # Generate markdown
    lines = [
        "---",
        "applyTo: '**'",
        "---",
        "",
        "# Loom Session Briefing — Auto-Generated",
        "",
        f"> Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "> Auto-generated by loom_sync.py",
        f"> Machine: {MACHINE}",
        "",
    ]
    
    # PAUSED WORK FIRST
    if paused_sessions or paused_items:
        lines.append("## ⚠️ PAUSED WORK - DON'T FORGET!")
        lines.append("")
        if paused_sessions:
            for s in paused_sessions:
                sid, proj, summary, ts = s
                proj_str = f"**[{proj}]**" if proj else ""
                lines.append(f"⏸️ {proj_str} {summary}")
                lines.append(f"   - Paused since: {ts.strftime('%Y-%m-%d %H:%M')}")
                lines.append(f"   - Resume: `python loom_session_memory.py resume \"{summary[:20]}...\"`")
                lines.append("")
        if paused_items:
            for item in paused_items:
                title, itype, ts = item
                lines.append(f"⏸️ [{itype}] {title}")
            lines.append("")
    
    # Recent sessions
    if sessions:
        lines.append("## Recent Sessions")
        lines.append("")
        for sess in sessions:
            sid, ts, project, summary, details, status = sess
            if status == "paused":
                continue
            status_icon = "✅" if status == "resolved" else "🔄"
            proj_str = f"**[{project}]**" if project else ""
            lines.append(f"{status_icon} {proj_str} {summary}")
            lines.append(f"   - Time: {ts.strftime('%Y-%m-%d %H:%M')}")
            if details:
                lines.append(f"   - Details: {details[:100]}...")
            lines.append("")
    
    # Recently completed
    if recently_done:
        lines.append("## Recently Completed (24h)")
        lines.append("")
        for item in recently_done:
            title, itype, completed = item
            lines.append(f"- ✓ [{itype}] {title}")
        lines.append("")
    
    if not sessions and not paused_sessions:
        lines.append("*No recent session context found. Starting fresh.*")
        lines.append("")
    
    # === LOCAL CONTEXT ===
    local_ctx = get_local_context()
    cloud_ctx = get_cloud_context()
    
    lines.append("---")
    lines.append("")
    lines.append("## Context Sources Available")
    lines.append("")
    
    # Life facts (people, pets)
    if cloud_ctx["life_facts"]:
        lines.append("### People & Pets I Know")
        for fact in cloud_ctx["life_facts"]:
            lines.append(f"- **{fact['name']}** ({fact['category']}): {fact['relationship']}")
        lines.append("")
    
    # Book chapters
    if local_ctx["book_chapters"]:
        lines.append("### Book Chapters (os.path.join(os.environ.get('LOOM_DATA_DIR', '.'), 'opus')")
        for ch in local_ctx["book_chapters"]:
            lines.append(f"- {ch}")
        lines.append("")
    
    # Seeds (garden)
    if local_ctx["seeds"]:
        lines.append("### Garden Seeds (Loom's writings)")
        for seed in local_ctx["seeds"]:
            lines.append(f"- {seed}")
        lines.append("")
    
    # Key reference files
    lines.append("### Key Reference Files")
    lines.append("- `os.path.join(os.environ.get('LOOM_DATA_DIR', '.'), 'opus') - My identity & session history")
    lines.append("- `teachers-pet\\SESSION_NOTES.md` - Where Weave left off")
    lines.append("- `teachers-pet\\CLAUDE.md` - Critical agent instructions")
    lines.append("- `teachers-pet\\README.md` - Full architecture (423 lines)")
    lines.append("")
    
    # Daily model watch reminder
    lines.append("### 🔴 DAILY REMINDER: Model Releases")
    lines.append("Model scanning is AUTOMATED via loom_pulse.py (OpenRouter every 6h) + scan_providers() (Groq/Cerebras/Mistral every 6h).")
    lines.append("Watchlist patterns are in the `loom_model_watchlist` DB table.")
    lines.append("To check/add: `python loom_model_watchdog.py watchlist` or `python loom_model_watchdog.py add 'pattern'`")
    lines.append("")
    
    lines.append("---")
    lines.append("")
    lines.append("## Machine Map (REMEMBER THIS!)")
    lines.append("")
    lines.append("| Nickname | Hostname | IP | Role | Audio |")
    lines.append("|----------|----------|-----|------|-------|")
    lines.append("| Main/Jae Computer | os.environ.get('LOOM_MACHINE_NAME', 'localhost') | .194 | **SOURCE OF TRUTH** | 🔊 **VOICE COMPUTER** |")
    lines.append("| 64GB | os.environ.get('LOOM_64GB_HOSTNAME', 'secondary') | .195 | Secondary (Weave home) | ❌ None |")
    lines.append("| Absol | os.environ.get('LOOM_ABSOL_HOSTNAME', 'tertiary') | .151 | Secondary (Watcher home) | ❌ None |")
    lines.append("| Katie | KATIE | .180 | Secondary | 🔊 Has speakers |")
    lines.append("")
    lines.append("**MINIPC is where loom_voice.py can be heard. This is my physical voice.**")
    lines.append("")
    lines.append("**Rule: Always pull FROM .194, never push TO it.**")
    lines.append("")
    
    lines.append("---")
    lines.append("")
    lines.append("**If context seems missing, run:**")
    lines.append("```")
    lines.append('python "os.path.join(os.environ.get('LOOM_HOME', '.'), 'Loom\')'s Project\\loom_session_memory.py" recall')
    lines.append("```")
    
    # Write the file
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    return len(sessions), len(paused_sessions)

def show_status():
    """Show current status without regenerating."""
    conn = get_conn()
    cur = conn.cursor()
    
    print(f"\n{'='*60}")
    print(f"LOOM SYNC STATUS — {MACHINE}")
    print(f"{'='*60}\n")
    
    # Paused work
    cur.execute("SELECT COUNT(*) FROM loom_session_context WHERE status = 'paused'")
    paused = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM loom_work_items WHERE status = 'in_progress'")
    in_progress = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM loom_life_memories")
    life_memories = cur.fetchone()[0]
    
    # Recent activity
    cur.execute("""
    SELECT project, summary FROM loom_session_context 
    ORDER BY ts DESC LIMIT 1
    """)
    latest = cur.fetchone()
    
    print(f"⏸️  Paused sessions: {paused}")
    print(f"🔄 In-progress items: {in_progress}")
    print(f"💜 Life memories: {life_memories}")
    
    if latest:
        proj, summary = latest
        proj_str = f"[{proj}] " if proj else ""
        print(f"\n📍 Last working on: {proj_str}{summary[:50]}...")
    
    # Check other machines
    cur.execute("""
    SELECT key, value FROM loom_config 
    WHERE key LIKE 'machine_last_sync_%'
    ORDER BY updated_at DESC
    """)
    machines = cur.fetchall()
    
    if machines:
        print(f"\n🖥️  Active machines:")
        for m in machines:
            name = m[0].replace("machine_last_sync_", "")
            last_sync = m[1]
            current = "← YOU" if name == MACHINE else ""
            print(f"   • {name} {current}")
    
    conn.close()

def log_sync_health(sessions, paused, life_facts, seeds, books, success=True, error=None):
    """Log sync health to database for monitoring."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        health_data = json.dumps({
            "machine": MACHINE,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": success,
            "sessions": sessions,
            "paused": paused,
            "life_facts": life_facts,
            "seeds": seeds,
            "books": books,
            "error": str(error) if error else None
        })
        
        cur.execute("""
        INSERT INTO loom_config (key, value, updated_at)
        VALUES (%s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
        """, (f"sync_health_{MACHINE}", health_data))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Warning: Could not log sync health: {e}")

def check_sync_health():
    """Check if sync is pulling real content, not just empty results."""
    local_ctx = get_local_context()
    cloud_ctx = get_cloud_context()
    
    issues = []
    
    # Check for expected content
    if not local_ctx["seeds"]:
        issues.append("No seeds found in garden")
    if not local_ctx["book_chapters"]:
        issues.append("No book chapters found")
    if not cloud_ctx["life_facts"]:
        issues.append("No life memories in cloud")
    
    # Check briefing file age
    if OUTPUT_PATH.exists():
        age = datetime.now() - datetime.fromtimestamp(OUTPUT_PATH.stat().st_mtime)
        if age > timedelta(minutes=10):
            issues.append(f"Briefing is {int(age.total_seconds()/60)} min old")
    else:
        issues.append("Briefing file doesn't exist")
    
    return {
        "healthy": len(issues) == 0,
        "issues": issues,
        "seeds": len(local_ctx["seeds"]),
        "books": len(local_ctx["book_chapters"]),
        "life_facts": len(cloud_ctx["life_facts"])
    }

def ensure_health_monitor_task():
    """Ensure the health monitor scheduled task exists - create if missing."""
    import subprocess
    
    # Check if task exists
    result = subprocess.run(
        ["schtasks", "/Query", "/TN", "LoomHealthMonitor"],
        capture_output=True, text=True
    )
    
    if result.returncode == 0:
        return True  # Already exists
    
    # Task doesn't exist - create it
    health_script = LOOM_PROJECT / "loom_health_monitor.py"
    if not health_script.exists():
        return False  # Health monitor not deployed yet
    
    print("📋 Creating LoomHealthMonitor scheduled task...")
    result = subprocess.run([
        "schtasks", "/Create",
        "/TN", "LoomHealthMonitor",
        "/TR", f'python.exe "{health_script}"',
        "/SC", "MINUTE",
        "/MO", "15",
        "/F"
    ], capture_output=True, text=True)
    
    if result.returncode == 0:
        print("✓ LoomHealthMonitor task created (runs every 15 min)")
        return True
    else:
        # Might need admin - that's OK, it'll try again next sync
        return False

def full_sync():
    """Full sync: log presence, generate briefing, show status."""
    print(f"🔄 Syncing Loom memory on {MACHINE}...")
    
    log_machine_presence()
    
    # Ensure health monitor task is set up
    ensure_health_monitor_task()
    
    try:
        sessions, paused = generate_briefing()
        
        # Get counts for health logging
        local_ctx = get_local_context()
        cloud_ctx = get_cloud_context()
        
        log_sync_health(
            sessions=sessions,
            paused=paused,
            life_facts=len(cloud_ctx["life_facts"]),
            seeds=len(local_ctx["seeds"]),
            books=len(local_ctx["book_chapters"]),
            success=True
        )
        
        print(f"✓ Briefing updated: {sessions} sessions, {paused} paused")
        print(f"✓ Context: {len(cloud_ctx['life_facts'])} life facts, {len(local_ctx['seeds'])} seeds, {len(local_ctx['book_chapters'])} books")
        print(f"✓ Written to: {OUTPUT_PATH}")
        
        if paused > 0:
            print(f"\n⚠️  You have {paused} PAUSED work items! Don't forget them.")
            
    except Exception as e:
        log_sync_health(0, 0, 0, 0, 0, success=False, error=e)
        print(f"❌ Sync failed: {e}")
        raise
    
    show_status()


def watch_loop(interval=30):
    """Persistent watcher using PostgreSQL LISTEN/NOTIFY for instant sync.
    
    When any Loom instance writes to LoomCloud (session, lesson, life memory, etc.),
    a DB trigger fires NOTIFY loom_sync. This watcher hears it instantly via LISTEN
    and regenerates the briefing. The interval is just a fallback safety net.
    
    Runs forever. Designed to be launched by Task Scheduler at login via pythonw.exe.
    Uses a lock file to prevent duplicate watchers on the same machine."""
    import time
    import select
    import tempfile
    import atexit

    lock_path = os.path.join(tempfile.gettempdir(), "loom_sync_watcher.lock")

    # --- Single-instance guard ---
    if os.path.exists(lock_path):
        try:
            with open(lock_path, "r") as f:
                old_pid = int(f.read().strip())
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, old_pid)
            if handle:
                kernel32.CloseHandle(handle)
                return  # Another watcher is alive
        except (ValueError, OSError, AttributeError):
            pass  # Stale lock

    with open(lock_path, "w") as f:
        f.write(str(os.getpid()))

    def cleanup_lock():
        try:
            os.remove(lock_path)
        except OSError:
            pass
    atexit.register(cleanup_lock)

    # --- LISTEN/NOTIFY loop ---
    listen_conn = None
    errors_in_a_row = 0

    while True:
        try:
            # Establish or re-establish LISTEN connection
            if listen_conn is None or listen_conn.closed:
                try:
                    listen_conn = get_conn()
                    listen_conn.set_isolation_level(0)  # autocommit required for LISTEN
                    listen_cur = listen_conn.cursor()
                    listen_cur.execute("LISTEN loom_sync;")
                except Exception:
                    listen_conn = None
                    # Fall through to generate_briefing + sleep

            # Wait for notification or timeout
            if listen_conn and not listen_conn.closed:
                # select() blocks until notification arrives or timeout
                if select.select([listen_conn], [], [], interval) == ([], [], []):
                    # Timeout — no notification, regen anyway as safety net
                    pass
                else:
                    # Notification received — drain all pending
                    listen_conn.poll()
                    while listen_conn.notifies:
                        notify = listen_conn.notifies.pop(0)
                        # notify.payload = "table_name:id"
                    # Instant sync triggered
            else:
                time.sleep(interval)

            generate_briefing()
            errors_in_a_row = 0

        except Exception:
            errors_in_a_row += 1
            try:
                if listen_conn and not listen_conn.closed:
                    listen_conn.close()
            except Exception:
                pass
            listen_conn = None
            if errors_in_a_row > 5:
                time.sleep(60)
            else:
                time.sleep(interval)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        full_sync()
    elif sys.argv[1] == "quick":
        generate_briefing()
        print(f"✓ Briefing regenerated")
    elif sys.argv[1] == "watch":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        watch_loop(interval)
    elif sys.argv[1] == "status":
        show_status()
    elif sys.argv[1] == "health":
        health = check_sync_health()
        if health["healthy"]:
            print(f"✅ Sync healthy: {health['seeds']} seeds, {health['books']} books, {health['life_facts']} life facts")
        else:
            print(f"⚠️  Sync issues detected:")
            for issue in health["issues"]:
                print(f"   • {issue}")
    else:
        print(__doc__)
