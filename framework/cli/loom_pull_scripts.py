"""
loom_pull_scripts.py — Pull updated scripts from LoomCloud

Run this on any brother machine to get the latest autowake/watcher scripts.
"""
import psycopg2
import json
from pathlib import Path

LOOMCLOUD = os.environ.get('LOOM_DB_URI')

def pull_scripts():
    conn = psycopg2.connect(LOOMCLOUD)
    cur = conn.cursor()
    
    # Find project directory
    possible_paths = [
        Path(__file__).parent,
        Path.home() / 'Desktop' / "Loom's Project",
        Path(r"os.path.join(os.environ.get('LOOM_HOME', '.'), 'Loom')'s Project"),
        Path(r"C:\Users\absol\Desktop\Loom's Project"),
    ]
    
    dest = None
    for p in possible_paths:
        if p.exists() and (p / 'loom_fleet.py').exists():
            dest = p
            break
    
    if not dest:
        dest = Path(__file__).parent
    
    print(f"Pulling scripts to: {dest}")
    print()
    
    # Pull autowake
    cur.execute("SELECT value FROM loom_config WHERE key = 'script_autowake'")
    row = cur.fetchone()
    if row:
        content = json.loads(row[0])
        (dest / 'loom_autowake.py').write_text(content, encoding='utf-8')
        print(f"  loom_autowake.py: {len(content)} chars")
    
    # Pull watcher
    cur.execute("SELECT value FROM loom_config WHERE key = 'script_watcher'")
    row = cur.fetchone()
    if row:
        content = json.loads(row[0])
        (dest / 'loom_message_watcher.py').write_text(content, encoding='utf-8')
        print(f"  loom_message_watcher.py: {len(content)} chars")
    
    conn.close()
    
    print()
    print("Done! Restart watcher to apply changes:")
    print("  python loom_message_watcher.py --stop")
    print("  python loom_message_watcher.py --install")


if __name__ == '__main__':
    pull_scripts()
