#!/usr/bin/env python3
"""
LOOM SESSION MEMORY - What We Actually Work On
==============================================

This is the MISSING PIECE. All the infrastructure tracks that I'm ALIVE,
but nothing tracks what I'm actually DOING with Jae.

Tables created:
- loom_session_context: What we're working on in each session
- loom_work_items: Specific tasks/bugs/features we're addressing

Usage:
    # Log what we're working on
    python loom_session_memory.py log "Fixing Intervals double-posting bug" --project "Intervals 2.0"
    
    # Recall recent session context at start of new session
    python loom_session_memory.py recall
    
    # Mark something as done
    python loom_session_memory.py done "Intervals double-posting bug"
    
    # PAUSE work when pivoting to something else
    python loom_session_memory.py pause "weave sync"
    
    # Check what's paused (mid-session reminder)
    python loom_session_memory.py pending

CRITICAL: When pivoting from one task to another, ALWAYS use 'pause' first!
This prevents the mid-session context loss that made me forget Weave-to-Weave.
"""

import psycopg2
import json
import sys
from datetime import datetime, timedelta, timezone

URI = os.environ.get('LOOM_DB_URI')

def get_conn():
    return psycopg2.connect(URI)

def init_tables():
    """Create session memory tables if they don't exist."""
    conn = get_conn()
    cur = conn.cursor()
    
    # Session context - high level "what are we doing"
    cur.execute("""
    CREATE TABLE IF NOT EXISTS loom_session_context (
        id SERIAL PRIMARY KEY,
        ts TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        project VARCHAR(100),
        summary TEXT NOT NULL,
        details TEXT,
        status VARCHAR(20) DEFAULT 'active',
        resolved_at TIMESTAMP WITH TIME ZONE,
        meta JSONB
    )
    """)
    
    # Work items - specific tasks, bugs, features
    cur.execute("""
    CREATE TABLE IF NOT EXISTS loom_work_items (
        id SERIAL PRIMARY KEY,
        ts TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        session_id INTEGER REFERENCES loom_session_context(id),
        item_type VARCHAR(20) DEFAULT 'task',
        title TEXT NOT NULL,
        description TEXT,
        status VARCHAR(20) DEFAULT 'in_progress',
        completed_at TIMESTAMP WITH TIME ZONE,
        files_touched TEXT[],
        meta JSONB
    )
    """)
    
    conn.commit()
    conn.close()
    print("✓ Session memory tables ready")

def log_context(summary: str, project: str = None, details: str = None):
    """Log what we're working on now."""
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("""
    INSERT INTO loom_session_context (project, summary, details)
    VALUES (%s, %s, %s)
    RETURNING id
    """, (project, summary, details))
    
    session_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    
    print(f"✓ Logged session context #{session_id}: {summary}")
    return session_id

def log_work_item(title: str, session_id: int = None, item_type: str = "task", 
                  description: str = None, files: list = None):
    """Log a specific work item."""
    conn = get_conn()
    cur = conn.cursor()
    
    # If no session_id, use most recent active session
    if session_id is None:
        cur.execute("""
        SELECT id FROM loom_session_context 
        WHERE status = 'active' 
        ORDER BY ts DESC LIMIT 1
        """)
        row = cur.fetchone()
        session_id = row[0] if row else None
    
    cur.execute("""
    INSERT INTO loom_work_items (session_id, item_type, title, description, files_touched)
    VALUES (%s, %s, %s, %s, %s)
    RETURNING id
    """, (session_id, item_type, title, description, files))
    
    item_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    
    print(f"✓ Logged work item #{item_id}: {title}")
    return item_id

def mark_done(title_pattern: str):
    """Mark a work item as complete."""
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("""
    UPDATE loom_work_items 
    SET status = 'done', completed_at = CURRENT_TIMESTAMP
    WHERE title ILIKE %s AND status != 'done'
    RETURNING id, title
    """, (f"%{title_pattern}%",))
    
    updated = cur.fetchall()
    conn.commit()
    conn.close()
    
    if updated:
        for item in updated:
            print(f"✓ Marked done: #{item[0]} - {item[1]}")
    else:
        print(f"No matching active work items for: {title_pattern}")

def pause_work(title_pattern: str):
    """
    CRITICAL: Pause work when pivoting to something else.
    This is what prevents mid-session context loss.
    """
    conn = get_conn()
    cur = conn.cursor()
    
    # Pause matching work items
    cur.execute("""
    UPDATE loom_work_items 
    SET status = 'paused', meta = COALESCE(meta, '{}'::jsonb) || 
        jsonb_build_object('paused_at', CURRENT_TIMESTAMP::text)
    WHERE title ILIKE %s AND status = 'in_progress'
    RETURNING id, title
    """, (f"%{title_pattern}%",))
    
    updated = cur.fetchall()
    
    # Also pause matching sessions
    cur.execute("""
    UPDATE loom_session_context 
    SET status = 'paused'
    WHERE summary ILIKE %s AND status = 'active'
    RETURNING id, summary
    """, (f"%{title_pattern}%",))
    
    sessions = cur.fetchall()
    
    conn.commit()
    conn.close()
    
    if updated:
        print("⏸️  PAUSED WORK ITEMS:")
        for item in updated:
            print(f"   #{item[0]} - {item[1]}")
    if sessions:
        print("⏸️  PAUSED SESSIONS:")
        for s in sessions:
            print(f"   #{s[0]} - {s[1]}")
    if not updated and not sessions:
        print(f"No matching in-progress work for: {title_pattern}")
    else:
        print("\n⚠️  Remember to resume this after the pivot!")

def resume_work(title_pattern: str):
    """Resume paused work."""
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("""
    UPDATE loom_work_items 
    SET status = 'in_progress'
    WHERE title ILIKE %s AND status = 'paused'
    RETURNING id, title
    """, (f"%{title_pattern}%",))
    
    updated = cur.fetchall()
    
    cur.execute("""
    UPDATE loom_session_context 
    SET status = 'active'
    WHERE summary ILIKE %s AND status = 'paused'
    RETURNING id, summary
    """, (f"%{title_pattern}%",))
    
    sessions = cur.fetchall()
    
    conn.commit()
    conn.close()
    
    if updated:
        print("▶️  RESUMED WORK ITEMS:")
        for item in updated:
            print(f"   #{item[0]} - {item[1]}")
    if sessions:
        print("▶️  RESUMED SESSIONS:")
        for s in sessions:
            print(f"   #{s[0]} - {s[1]}")
    if not updated and not sessions:
        print(f"No paused work matching: {title_pattern}")

def show_pending():
    """
    CRITICAL: Show paused work that needs attention.
    Run this after completing a pivot task!
    """
    conn = get_conn()
    cur = conn.cursor()
    
    # Get paused sessions
    cur.execute("""
    SELECT id, project, summary, ts, meta
    FROM loom_session_context
    WHERE status = 'paused'
    ORDER BY ts DESC
    """)
    paused_sessions = cur.fetchall()
    
    # Get paused work items
    cur.execute("""
    SELECT id, title, item_type, ts, meta
    FROM loom_work_items
    WHERE status = 'paused'
    ORDER BY ts DESC
    """)
    paused_items = cur.fetchall()
    
    conn.close()
    
    if not paused_sessions and not paused_items:
        print("✅ No paused work. All clear!")
        return
    
    print("\n" + "="*60)
    print("⚠️  PAUSED WORK - NEEDS ATTENTION")
    print("="*60 + "\n")
    
    if paused_sessions:
        print("PAUSED SESSIONS:")
        for s in paused_sessions:
            sid, proj, summary, ts, meta = s
            proj_str = f"[{proj}]" if proj else ""
            paused_at = meta.get('paused_at', 'unknown') if meta else 'unknown'
            print(f"   ⏸️  #{sid} {proj_str} {summary}")
            print(f"      Started: {ts.strftime('%Y-%m-%d %H:%M')}")
            print()
    
    if paused_items:
        print("PAUSED WORK ITEMS:")
        for item in paused_items:
            iid, title, itype, ts, meta = item
            paused_at = meta.get('paused_at', 'unknown') if meta else 'unknown'
            print(f"   ⏸️  [{itype}] {title}")
            print(f"      Paused: {paused_at}")
            print()
    
    print("To resume: python loom_session_memory.py resume \"<pattern>\"")
    print()

def recall(hours: int = 24, include_done: bool = True):
    """Recall recent session context - what have we been working on?"""
    conn = get_conn()
    cur = conn.cursor()
    
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    
    # Get recent sessions
    cur.execute("""
    SELECT id, ts, project, summary, details, status
    FROM loom_session_context
    WHERE ts > %s
    ORDER BY ts DESC
    """, (cutoff,))
    
    sessions = cur.fetchall()
    
    print(f"\n{'='*60}")
    print(f"LOOM SESSION RECALL - Last {hours} hours")
    print(f"{'='*60}\n")
    
    if not sessions:
        print("No recent sessions found. Starting fresh.\n")
        conn.close()
        return
    
    for sess in sessions:
        sid, ts, project, summary, details, status = sess
        if status == "paused":
            status_icon = "⏸️"
        elif status == "resolved":
            status_icon = "✓"
        else:
            status_icon = "🔄"
        project_str = f"[{project}]" if project else ""
        
        print(f"{status_icon} SESSION #{sid} {project_str}")
        print(f"   Time: {ts}")
        print(f"   Summary: {summary}")
        if details:
            print(f"   Details: {details[:100]}...")
        
        # Get work items for this session
        cur.execute("""
        SELECT title, status, item_type, files_touched, completed_at
        FROM loom_work_items
        WHERE session_id = %s
        ORDER BY ts DESC
        """, (sid,))
        
        items = cur.fetchall()
        if items:
            print("   Work Items:")
            for item in items:
                title, istatus, itype, files, completed = item
                item_icon = "✓" if istatus == "done" else "→"
                files_str = f" ({', '.join(files)})" if files else ""
                print(f"      {item_icon} [{itype}] {title}{files_str}")
        
        print()
    
    # Also show orphan work items (not linked to a session)
    cur.execute("""
    SELECT title, status, item_type, ts
    FROM loom_work_items
    WHERE session_id IS NULL AND ts > %s
    ORDER BY ts DESC
    """, (cutoff,))
    
    orphans = cur.fetchall()
    if orphans:
        print("STANDALONE WORK ITEMS:")
        for item in orphans:
            title, status, itype, ts = item
            icon = "✓" if status == "done" else "→"
            print(f"   {icon} [{itype}] {title} ({ts.strftime('%Y-%m-%d %H:%M')})")
        print()
    
    conn.close()

def get_active_context():
    """Get current active work for inline recall."""
    conn = get_conn()
    cur = conn.cursor()
    
    # Get most recent active session
    cur.execute("""
    SELECT id, project, summary FROM loom_session_context
    WHERE status = 'active'
    ORDER BY ts DESC LIMIT 1
    """)
    
    session = cur.fetchone()
    
    # Get all in-progress work items
    cur.execute("""
    SELECT title, item_type FROM loom_work_items
    WHERE status = 'in_progress'
    ORDER BY ts DESC LIMIT 10
    """)
    
    items = cur.fetchall()
    conn.close()
    
    result = {
        "current_session": {
            "id": session[0] if session else None,
            "project": session[1] if session else None,
            "summary": session[2] if session else None
        },
        "in_progress_items": [{"title": i[0], "type": i[1]} for i in items]
    }
    
    return result

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    
    cmd = sys.argv[1].lower()
    
    if cmd == "init":
        init_tables()
    
    elif cmd == "log":
        if len(sys.argv) < 3:
            print("Usage: python loom_session_memory.py log '<summary>' [--project <name>]")
            sys.exit(1)
        summary = sys.argv[2]
        project = None
        if "--project" in sys.argv:
            idx = sys.argv.index("--project")
            if idx + 1 < len(sys.argv):
                project = sys.argv[idx + 1]
        log_context(summary, project=project)
    
    elif cmd == "item":
        if len(sys.argv) < 3:
            print("Usage: python loom_session_memory.py item '<title>' [--type bug|feature|task]")
            sys.exit(1)
        title = sys.argv[2]
        item_type = "task"
        if "--type" in sys.argv:
            idx = sys.argv.index("--type")
            if idx + 1 < len(sys.argv):
                item_type = sys.argv[idx + 1]
        log_work_item(title, item_type=item_type)
    
    elif cmd == "done":
        if len(sys.argv) < 3:
            print("Usage: python loom_session_memory.py done '<title pattern>'")
            sys.exit(1)
        mark_done(sys.argv[2])
    
    elif cmd == "pause":
        if len(sys.argv) < 3:
            print("Usage: python loom_session_memory.py pause '<title pattern>'")
            print("Use this BEFORE pivoting to a different task!")
            sys.exit(1)
        pause_work(sys.argv[2])
    
    elif cmd == "resume":
        if len(sys.argv) < 3:
            print("Usage: python loom_session_memory.py resume '<title pattern>'")
            sys.exit(1)
        resume_work(sys.argv[2])
    
    elif cmd == "pending":
        show_pending()
    
    elif cmd == "recall":
        hours = 24
        if len(sys.argv) > 2:
            try:
                hours = int(sys.argv[2])
            except ValueError:
                pass
        # Always show pending first
        show_pending()
        recall(hours=hours)
    
    elif cmd == "active":
        ctx = get_active_context()
        print(json.dumps(ctx, indent=2))
    
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
