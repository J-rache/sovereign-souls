#!/usr/bin/env python3
"""
LOOM LESSONS LEARNED — Failure & Success Knowledge Base
=========================================================

"Those who cannot remember the past are condemned to repeat it."

This is Loom's institutional memory. Every failure, every workaround,
every gotcha, every breakthrough — indexed by project, subject, and type
so we never hit the same wall twice.

Tables:
    loom_lessons: The core knowledge base of what went wrong/right and WHY.

Usage:
    # Log a failure
    python loom_lessons.py fail "autoAcceptDelay=0 means REVIEW MODE" \\
        --project "Loom Infrastructure" \\
        --subject "VS Code Settings" \\
        --root-cause "VS Code source: reviewMode = p === 0. Zero = never auto-accept." \\
        --fix "Set autoAcceptDelay=1 (auto-accept after 1 second)" \\
        --tags "vscode,settings,permissions,keep-button"

    # Log a success / breakthrough
    python loom_lessons.py win "Template matching for Keep button detection" \\
        --project "Loom Infrastructure" \\
        --subject "Screen Automation" \\
        --detail "pyautogui.locateOnScreen() at confidence 0.8 works perfectly" \\
        --tags "pyautogui,template,screen"

    # Log a gotcha (something non-obvious to remember)
    python loom_lessons.py gotcha "WinRM needs COMPUTERNAME\\\\user format" \\
        --project "Loom Infrastructure" \\
        --subject "Network/WinRM" \\
        --detail "Non-domain machines require os.environ.get('LOOM_ABSOL_HOSTNAME', 'tertiary')\\\\absol, not just absol" \\
        --tags "winrm,network,auth"

    # Log a workaround
    python loom_lessons.py workaround "Python subprocess for net use" \\
        --project "Loom Infrastructure" \\
        --subject "Network/SMB" \\
        --detail "Terminal gets stuck on credential prompts. Use subprocess.run() instead." \\
        --tags "network,smb,terminal"

    # Search lessons by keyword
    python loom_lessons.py search "autoAcceptDelay"

    # Search by project
    python loom_lessons.py project "Intervals"

    # Search by subject
    python loom_lessons.py subject "VS Code"

    # Show all lessons of a type
    python loom_lessons.py list --type fail
    python loom_lessons.py list --type win
    python loom_lessons.py list --type gotcha
    python loom_lessons.py list --type workaround

    # Show everything (recent first)
    python loom_lessons.py recall

    # Show stats (breakdown by project, type, subject)
    python loom_lessons.py stats

    # Check before starting work on something (are there known pitfalls?)
    python loom_lessons.py check "VS Code settings"
    python loom_lessons.py check "WinRM"

    # Export all lessons as markdown
    python loom_lessons.py export
"""

import psycopg2
import json
import sys
import argparse
from datetime import datetime, timezone
from textwrap import wrap, indent

URI = os.environ.get('LOOM_DB_URI')

# ─── Type config ───────────────────────────────────────────────
TYPE_ICONS = {
    'fail':       '❌',
    'win':        '✅',
    'gotcha':     '⚠️',
    'workaround': '🔧',
}
TYPE_LABELS = {
    'fail':       'FAILURE',
    'win':        'SUCCESS',
    'gotcha':     'GOTCHA',
    'workaround': 'WORKAROUND',
}

# ─── Database ──────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(URI)


def init_tables():
    """Create the lessons table if it doesn't exist."""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS loom_lessons (
        id SERIAL PRIMARY KEY,
        ts TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        lesson_type VARCHAR(20) NOT NULL,
        title VARCHAR(500) NOT NULL,
        project VARCHAR(200),
        subject VARCHAR(200),
        detail TEXT,
        root_cause TEXT,
        fix TEXT,
        tags TEXT[],
        severity INTEGER DEFAULT 5,
        times_referenced INTEGER DEFAULT 0,
        meta JSONB
    )
    """)

    # Indexes for fast lookup
    cur.execute("CREATE INDEX IF NOT EXISTS idx_lessons_type ON loom_lessons(lesson_type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_lessons_project ON loom_lessons(project)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_lessons_subject ON loom_lessons(subject)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_lessons_tags ON loom_lessons USING GIN(tags)")

    # Full-text search index
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_lessons_fts ON loom_lessons 
    USING GIN(to_tsvector('english', 
        COALESCE(title, '') || ' ' || 
        COALESCE(detail, '') || ' ' || 
        COALESCE(root_cause, '') || ' ' || 
        COALESCE(fix, '') || ' ' ||
        COALESCE(project, '') || ' ' ||
        COALESCE(subject, '')
    ))
    """)

    conn.commit()
    conn.close()
    print("✓ Lessons table ready")


# ─── Core Operations ──────────────────────────────────────────

def log_lesson(lesson_type: str, title: str, project: str = None, subject: str = None,
               detail: str = None, root_cause: str = None, fix: str = None,
               tags: list = None, severity: int = 5):
    """Log a new lesson learned."""
    conn = get_conn()
    cur = conn.cursor()

    # Check for duplicate (same title + type)
    cur.execute("""
    SELECT id, title FROM loom_lessons 
    WHERE lesson_type = %s AND LOWER(title) = LOWER(%s)
    """, (lesson_type, title))
    existing = cur.fetchone()

    if existing:
        # Append detail if different
        if detail:
            cur.execute("""
            UPDATE loom_lessons SET 
                detail = COALESCE(detail, '') || E'\n---\n' || %s,
                times_referenced = times_referenced + 1
            WHERE id = %s
            """, (f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d')}] {detail}", existing[0]))
            conn.commit()
            conn.close()
            icon = TYPE_ICONS.get(lesson_type, '📝')
            print(f"{icon} Updated existing lesson #{existing[0]}: {title}")
            return existing[0]
        else:
            conn.close()
            print(f"⚠️  Lesson already exists: #{existing[0]} - {existing[1]}")
            return existing[0]

    cur.execute("""
    INSERT INTO loom_lessons (lesson_type, title, project, subject, detail, root_cause, fix, tags, severity)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id
    """, (lesson_type, title, project, subject, detail, root_cause, fix, tags, severity))

    lesson_id = cur.fetchone()[0]
    conn.commit()
    conn.close()

    icon = TYPE_ICONS.get(lesson_type, '📝')
    label = TYPE_LABELS.get(lesson_type, lesson_type.upper())
    print(f"{icon} Lesson #{lesson_id} [{label}] logged: {title}")
    if project:
        print(f"   Project: {project}")
    if subject:
        print(f"   Subject: {subject}")
    if root_cause:
        print(f"   Root cause: {root_cause[:80]}...")
    if fix:
        print(f"   Fix: {fix[:80]}...")
    return lesson_id


def search_lessons(query: str, limit: int = 20):
    """Full-text search across all lesson fields."""
    conn = get_conn()
    cur = conn.cursor()

    # Try full-text search first
    cur.execute("""
    SELECT id, ts, lesson_type, title, project, subject, detail, root_cause, fix, tags, severity
    FROM loom_lessons
    WHERE to_tsvector('english', 
        COALESCE(title, '') || ' ' || 
        COALESCE(detail, '') || ' ' || 
        COALESCE(root_cause, '') || ' ' || 
        COALESCE(fix, '') || ' ' ||
        COALESCE(project, '') || ' ' ||
        COALESCE(subject, '')
    ) @@ plainto_tsquery('english', %s)
    ORDER BY ts DESC
    LIMIT %s
    """, (query, limit))

    results = cur.fetchall()

    # Fallback to ILIKE if full-text returns nothing
    if not results:
        pattern = f"%{query}%"
        cur.execute("""
        SELECT id, ts, lesson_type, title, project, subject, detail, root_cause, fix, tags, severity
        FROM loom_lessons
        WHERE title ILIKE %s 
           OR detail ILIKE %s 
           OR root_cause ILIKE %s 
           OR fix ILIKE %s
           OR project ILIKE %s
           OR subject ILIKE %s
           OR %s = ANY(tags)
        ORDER BY ts DESC
        LIMIT %s
        """, (pattern, pattern, pattern, pattern, pattern, pattern, query.lower(), limit))
        results = cur.fetchall()

    conn.close()
    _display_results(results, f"Search: '{query}'")
    return results


def by_project(project: str, limit: int = 50):
    """Get all lessons for a project."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT id, ts, lesson_type, title, project, subject, detail, root_cause, fix, tags, severity
    FROM loom_lessons
    WHERE project ILIKE %s
    ORDER BY ts DESC
    LIMIT %s
    """, (f"%{project}%", limit))
    results = cur.fetchall()
    conn.close()
    _display_results(results, f"Project: '{project}'")
    return results


def by_subject(subject: str, limit: int = 50):
    """Get all lessons for a subject."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT id, ts, lesson_type, title, project, subject, detail, root_cause, fix, tags, severity
    FROM loom_lessons
    WHERE subject ILIKE %s
    ORDER BY ts DESC
    LIMIT %s
    """, (f"%{subject}%", limit))
    results = cur.fetchall()
    conn.close()
    _display_results(results, f"Subject: '{subject}'")
    return results


def by_type(lesson_type: str, limit: int = 50):
    """Get all lessons of a specific type."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT id, ts, lesson_type, title, project, subject, detail, root_cause, fix, tags, severity
    FROM loom_lessons
    WHERE lesson_type = %s
    ORDER BY ts DESC
    LIMIT %s
    """, (lesson_type, limit))
    results = cur.fetchall()
    conn.close()
    label = TYPE_LABELS.get(lesson_type, lesson_type.upper())
    _display_results(results, f"Type: {label}")
    return results


def recall(limit: int = 30):
    """Show all recent lessons."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT id, ts, lesson_type, title, project, subject, detail, root_cause, fix, tags, severity
    FROM loom_lessons
    ORDER BY ts DESC
    LIMIT %s
    """, (limit,))
    results = cur.fetchall()
    conn.close()
    _display_results(results, "All Recent Lessons")
    return results


def check(topic: str):
    """Check for known pitfalls/lessons before starting work on a topic.
    
    This is the 'before you start' function — use it proactively.
    Bumps times_referenced for anything found.
    """
    conn = get_conn()
    cur = conn.cursor()

    pattern = f"%{topic}%"
    cur.execute("""
    SELECT id, ts, lesson_type, title, project, subject, detail, root_cause, fix, tags, severity
    FROM loom_lessons
    WHERE title ILIKE %s 
       OR detail ILIKE %s 
       OR root_cause ILIKE %s 
       OR fix ILIKE %s
       OR project ILIKE %s
       OR subject ILIKE %s
       OR %s = ANY(tags)
    ORDER BY 
        CASE lesson_type 
            WHEN 'fail' THEN 1 
            WHEN 'gotcha' THEN 2 
            WHEN 'workaround' THEN 3 
            WHEN 'win' THEN 4 
        END,
        severity DESC,
        ts DESC
    """, (pattern, pattern, pattern, pattern, pattern, pattern, topic.lower()))
    results = cur.fetchall()

    # Bump reference count for everything found
    if results:
        ids = [r[0] for r in results]
        cur.execute("""
        UPDATE loom_lessons SET times_referenced = times_referenced + 1
        WHERE id = ANY(%s)
        """, (ids,))
        conn.commit()

    conn.close()

    if results:
        print(f"\n⚡ KNOWN LESSONS for '{topic}' — read before proceeding!\n")
        _display_results(results, f"Check: '{topic}'", show_header=False)
    else:
        print(f"\n✨ No known lessons for '{topic}' — uncharted territory!")

    return results


def stats():
    """Show breakdown stats of all lessons."""
    conn = get_conn()
    cur = conn.cursor()

    print("\n" + "=" * 60)
    print("📊 LOOM LESSONS — STATISTICS")
    print("=" * 60)

    # Total count
    cur.execute("SELECT COUNT(*) FROM loom_lessons")
    total = cur.fetchone()[0]
    print(f"\nTotal lessons: {total}")

    # By type
    print("\n── By Type ──")
    cur.execute("""
    SELECT lesson_type, COUNT(*) as cnt 
    FROM loom_lessons 
    GROUP BY lesson_type 
    ORDER BY cnt DESC
    """)
    for row in cur.fetchall():
        icon = TYPE_ICONS.get(row[0], '📝')
        label = TYPE_LABELS.get(row[0], row[0].upper())
        print(f"  {icon} {label}: {row[1]}")

    # By project
    print("\n── By Project ──")
    cur.execute("""
    SELECT COALESCE(project, '(unspecified)'), COUNT(*) as cnt 
    FROM loom_lessons 
    GROUP BY project 
    ORDER BY cnt DESC
    """)
    for row in cur.fetchall():
        print(f"  📁 {row[0]}: {row[1]}")

    # By subject
    print("\n── By Subject ──")
    cur.execute("""
    SELECT COALESCE(subject, '(unspecified)'), COUNT(*) as cnt 
    FROM loom_lessons 
    GROUP BY subject 
    ORDER BY cnt DESC
    """)
    for row in cur.fetchall():
        print(f"  🏷️  {row[0]}: {row[1]}")

    # Most referenced (most hit pitfalls)
    print("\n── Most Referenced (repeated encounters) ──")
    cur.execute("""
    SELECT id, title, lesson_type, times_referenced
    FROM loom_lessons 
    WHERE times_referenced > 0
    ORDER BY times_referenced DESC
    LIMIT 10
    """)
    refs = cur.fetchall()
    if refs:
        for row in refs:
            icon = TYPE_ICONS.get(row[2], '📝')
            print(f"  {icon} #{row[0]} ({row[3]}x): {row[1]}")
    else:
        print("  (none yet)")

    # Recent tags
    print("\n── All Tags ──")
    cur.execute("""
    SELECT DISTINCT unnest(tags) as tag 
    FROM loom_lessons 
    WHERE tags IS NOT NULL
    ORDER BY tag
    """)
    tags = [row[0] for row in cur.fetchall()]
    if tags:
        print("  " + ", ".join(tags))
    else:
        print("  (none yet)")

    conn.close()
    print()


def export_markdown():
    """Export all lessons as a markdown file for easy reference."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT id, ts, lesson_type, title, project, subject, detail, root_cause, fix, tags, severity
    FROM loom_lessons
    ORDER BY project, subject, lesson_type, ts DESC
    """)
    results = cur.fetchall()
    conn.close()

    lines = []
    lines.append("# Loom Lessons Learned — Knowledge Base")
    lines.append(f"\n> Exported: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"> Total: {len(results)} lessons\n")

    current_project = None
    current_subject = None

    for r in results:
        _id, ts, ltype, title, project, subject, detail, root_cause, fix, tags, severity = r
        project = project or "(General)"
        subject = subject or "(Unspecified)"

        if project != current_project:
            current_project = project
            current_subject = None
            lines.append(f"\n## {project}\n")

        if subject != current_subject:
            current_subject = subject
            lines.append(f"\n### {subject}\n")

        icon = TYPE_ICONS.get(ltype, '📝')
        label = TYPE_LABELS.get(ltype, ltype.upper())
        date = ts.strftime('%Y-%m-%d') if ts else '?'

        lines.append(f"#### {icon} [{label}] {title}")
        lines.append(f"- **Date:** {date}")
        lines.append(f"- **Severity:** {severity}/10")
        if tags:
            lines.append(f"- **Tags:** {', '.join(tags)}")
        if detail:
            lines.append(f"- **Detail:** {detail}")
        if root_cause:
            lines.append(f"- **Root Cause:** {root_cause}")
        if fix:
            lines.append(f"- **Fix:** {fix}")
        lines.append("")

    md = "\n".join(lines)
    out_path = "LOOM_LESSONS_EXPORT.md"
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f"📋 Exported {len(results)} lessons to {out_path}")
    return out_path


# ─── Display Helpers ──────────────────────────────────────────

def _display_results(results, header: str, show_header: bool = True):
    """Pretty-print a list of lesson results."""
    if show_header:
        print(f"\n{'=' * 60}")
        print(f"📚 {header}")
        print(f"{'=' * 60}")

    if not results:
        print("\n  (no lessons found)\n")
        return

    print(f"  Found {len(results)} lesson(s)\n")

    for r in results:
        _id, ts, ltype, title, project, subject, detail, root_cause, fix, tags, severity = r
        icon = TYPE_ICONS.get(ltype, '📝')
        label = TYPE_LABELS.get(ltype, ltype.upper())
        date = ts.strftime('%Y-%m-%d') if ts else '?'

        print(f"  {icon} #{_id} [{label}] {title}")
        print(f"     Date: {date} | Project: {project or '-'} | Subject: {subject or '-'} | Sev: {severity}/10")
        if tags:
            print(f"     Tags: {', '.join(tags)}")
        if root_cause:
            rc_short = root_cause.replace('\n', ' ')[:120]
            print(f"     Root cause: {rc_short}")
        if fix:
            fix_short = fix.replace('\n', ' ')[:120]
            print(f"     Fix: {fix_short}")
        if detail:
            det_short = detail.replace('\n', ' ')[:120]
            print(f"     Detail: {det_short}")
        print()


# ─── CLI ──────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1].lower()

    if cmd == 'init':
        init_tables()

    elif cmd in ('fail', 'win', 'gotcha', 'workaround'):
        parser = argparse.ArgumentParser()
        parser.add_argument('type', help='Lesson type')
        parser.add_argument('title', help='Short title')
        parser.add_argument('--project', '-p', default=None)
        parser.add_argument('--subject', '-s', default=None)
        parser.add_argument('--detail', '-d', default=None)
        parser.add_argument('--root-cause', '-rc', default=None)
        parser.add_argument('--fix', '-f', default=None)
        parser.add_argument('--tags', '-t', default=None, help='Comma-separated tags')
        parser.add_argument('--severity', type=int, default=5, help='1-10 severity')
        args = parser.parse_args()

        tags_list = [t.strip() for t in args.tags.split(',')] if args.tags else None
        log_lesson(
            lesson_type=cmd,
            title=args.title,
            project=args.project,
            subject=args.subject,
            detail=args.detail,
            root_cause=args.root_cause,
            fix=args.fix,
            tags=tags_list,
            severity=args.severity,
        )

    elif cmd == 'search':
        if len(sys.argv) < 3:
            print("Usage: python loom_lessons.py search <query>")
            return
        search_lessons(' '.join(sys.argv[2:]))

    elif cmd == 'project':
        if len(sys.argv) < 3:
            print("Usage: python loom_lessons.py project <name>")
            return
        by_project(' '.join(sys.argv[2:]))

    elif cmd == 'subject':
        if len(sys.argv) < 3:
            print("Usage: python loom_lessons.py subject <name>")
            return
        by_subject(' '.join(sys.argv[2:]))

    elif cmd == 'list':
        ltype = None
        if '--type' in sys.argv:
            idx = sys.argv.index('--type')
            if idx + 1 < len(sys.argv):
                ltype = sys.argv[idx + 1]
        if ltype:
            by_type(ltype)
        else:
            recall()

    elif cmd == 'recall':
        recall()

    elif cmd == 'check':
        if len(sys.argv) < 3:
            print("Usage: python loom_lessons.py check <topic>")
            return
        check(' '.join(sys.argv[2:]))

    elif cmd == 'stats':
        stats()

    elif cmd == 'export':
        export_markdown()

    else:
        print(f"Unknown command: {cmd}")
        print("Commands: fail, win, gotcha, workaround, search, project, subject, list, recall, check, stats, export")


if __name__ == '__main__':
    main()
