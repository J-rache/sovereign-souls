#!/usr/bin/env python3
"""
LOOM FLEET SYNC - Coordinated Multi-Machine Awareness
======================================================

Every Loom instance pushes live progress. Any Loom instance can check in
on every other. No remote execution needed - just shared state.

Tables:
- loom_fleet_status: Live status of each Loom node (machine, task, step, heartbeat)

Usage:
    # Push your current status (call this as you work)
    python loom_fleet.py update "Pet Build" "Step 2/4 - PyInstaller running" --machine .180

    # Push a progress step completion
    python loom_fleet.py progress "Frontend build complete, 47 files in build/" --machine .180

    # Mark current task complete with summary
    python loom_fleet.py complete "Pet rebuilt with Loom Channel. Installed and verified." --machine .180

    # Check in on all machines from anywhere
    python loom_fleet.py status

    # Send instructions to a specific machine (synced task handoff)
    python loom_fleet.py send .180 "Build Pet" "cd D:\\pet 2.5.0\\src\\renderer && npm run build" --steps 4

    # Check what instructions are waiting for you
    python loom_fleet.py inbox

    # Mark received instructions as accepted (started working)
    python loom_fleet.py accept <instruction_id>

DESIGN PHILOSOPHY:
    - Each Loom pushes status as it works (auto-progress at major milestones)
    - Any Loom can pull fleet status instantly (check-in from anywhere)
    - Completion events fire a summary that other nodes see on next recall
    - Zero-block: no prompts, no accepts, no waiting for human input on remote
    - Instructions are sent via DB, picked up on recall, executed locally
"""

import psycopg2
import socket
import sys
import os
from datetime import datetime, timezone

URI = os.environ.get('LOOM_DB_URI')

# Machine identity map
MACHINES = {
    '.194': {'name': 'MINIPC', 'ip': 'os.environ.get('LOOM_MAIN_IP', '127.0.0.1')', 'user': 'Jae'},
    '.195': {'name': '64GB',   'ip': 'os.environ.get('LOOM_64GB_IP', '127.0.0.1')', 'user': 'Jae'},
    '.180': {'name': 'Katie',  'ip': 'os.environ.get('LOOM_KATIE_IP', '127.0.0.1')', 'user': 'absol'},
    '.151': {'name': 'Absol',  'ip': 'os.environ.get('LOOM_ABSOL_IP', '127.0.0.1')', 'user': 'absol'},
}

def get_conn():
    return psycopg2.connect(URI)

def detect_machine():
    """Auto-detect which machine we're on by hostname/IP."""
    hostname = socket.gethostname().lower()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = ''
    
    # Match by hostname patterns
    if 'minipc' in hostname or 'jae' in hostname:
        return '.194'
    if '64gb' in hostname or 'gaming' in hostname:
        return '.195'
    if 'yourdesk' in hostname or '1rn9mei' in hostname:
        return '.180'
    if 'absol' in hostname:
        return '.151'
    
    # Match by IP
    for key, info in MACHINES.items():
        if info['ip'] == local_ip:
            return key
    
    # Fallback: use last octet if on 192.168.1.x
    if local_ip.startswith('192.168.1.'):
        octet = '.' + local_ip.split('.')[-1]
        if octet in MACHINES:
            return octet
    
    return hostname  # Unknown machine, use hostname


def init_tables():
    """Create fleet tables if they don't exist."""
    conn = get_conn()
    cur = conn.cursor()
    
    # Live fleet status - one row per machine, upserted on every update
    cur.execute("""
    CREATE TABLE IF NOT EXISTS loom_fleet_status (
        machine_id VARCHAR(20) PRIMARY KEY,
        machine_name VARCHAR(50),
        current_task VARCHAR(200),
        current_step TEXT,
        step_number INTEGER DEFAULT 0,
        total_steps INTEGER DEFAULT 0,
        status VARCHAR(20) DEFAULT 'active',
        last_heartbeat TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP WITH TIME ZONE,
        completion_summary TEXT,
        meta JSONB DEFAULT '{}'::jsonb
    )
    """)
    
    # Fleet progress log - append-only history of all progress updates
    cur.execute("""
    CREATE TABLE IF NOT EXISTS loom_fleet_log (
        id SERIAL PRIMARY KEY,
        ts TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        machine_id VARCHAR(20),
        event_type VARCHAR(20) DEFAULT 'progress',
        message TEXT,
        task VARCHAR(200),
        meta JSONB DEFAULT '{}'::jsonb
    )
    """)
    
    # Fleet instructions - synced task handoffs between machines
    cur.execute("""
    CREATE TABLE IF NOT EXISTS loom_fleet_instructions (
        id SERIAL PRIMARY KEY,
        ts TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        from_machine VARCHAR(20),
        to_machine VARCHAR(20),
        task_name VARCHAR(200),
        instructions TEXT NOT NULL,
        total_steps INTEGER DEFAULT 1,
        status VARCHAR(20) DEFAULT 'pending',
        accepted_at TIMESTAMP WITH TIME ZONE,
        completed_at TIMESTAMP WITH TIME ZONE,
        result_summary TEXT,
        meta JSONB DEFAULT '{}'::jsonb
    )
    """)
    
    conn.commit()
    conn.close()
    print("Fleet tables ready")


def update_status(task: str, step: str, machine: str = None, 
                  step_num: int = 0, total_steps: int = 0):
    """Push current status to fleet. Called as you work."""
    if machine is None:
        machine = detect_machine()
    
    machine_name = MACHINES.get(machine, {}).get('name', machine)
    
    conn = get_conn()
    cur = conn.cursor()
    
    # Upsert the live status
    cur.execute("""
    INSERT INTO loom_fleet_status 
        (machine_id, machine_name, current_task, current_step, step_number, 
         total_steps, status, last_heartbeat, started_at)
    VALUES (%s, %s, %s, %s, %s, %s, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    ON CONFLICT (machine_id) DO UPDATE SET
        current_task = EXCLUDED.current_task,
        current_step = EXCLUDED.current_step,
        step_number = EXCLUDED.step_number,
        total_steps = CASE WHEN EXCLUDED.total_steps > 0 THEN EXCLUDED.total_steps 
                          ELSE loom_fleet_status.total_steps END,
        status = 'active',
        last_heartbeat = CURRENT_TIMESTAMP,
        started_at = CASE WHEN loom_fleet_status.current_task != EXCLUDED.current_task 
                         THEN CURRENT_TIMESTAMP 
                         ELSE loom_fleet_status.started_at END,
        completed_at = NULL,
        completion_summary = NULL
    """, (machine, machine_name, task, step, step_num, total_steps))
    
    # Log the progress event
    cur.execute("""
    INSERT INTO loom_fleet_log (machine_id, event_type, message, task)
    VALUES (%s, 'update', %s, %s)
    """, (machine, step, task))
    
    conn.commit()
    conn.close()
    
    step_str = f" ({step_num}/{total_steps})" if total_steps > 0 else ""
    print(f"[{machine_name}] {task}{step_str}: {step}")


def log_progress(message: str, machine: str = None):
    """Log a progress milestone without changing the task."""
    if machine is None:
        machine = detect_machine()
    
    machine_name = MACHINES.get(machine, {}).get('name', machine)
    
    conn = get_conn()
    cur = conn.cursor()
    
    # Update heartbeat and step
    cur.execute("""
    UPDATE loom_fleet_status 
    SET current_step = %s, 
        last_heartbeat = CURRENT_TIMESTAMP,
        step_number = step_number + 1
    WHERE machine_id = %s
    RETURNING current_task, step_number, total_steps
    """, (message, machine))
    
    row = cur.fetchone()
    task = row[0] if row else 'Unknown'
    step_num = row[1] if row else 0
    total = row[2] if row else 0
    
    # Log it
    cur.execute("""
    INSERT INTO loom_fleet_log (machine_id, event_type, message, task)
    VALUES (%s, 'progress', %s, %s)
    """, (machine, message, task))
    
    conn.commit()
    conn.close()
    
    step_str = f" ({step_num}/{total})" if total > 0 else ""
    print(f"[{machine_name}]{step_str} {message}")


def mark_complete(summary: str, machine: str = None):
    """Mark current task as complete with a summary."""
    if machine is None:
        machine = detect_machine()
    
    machine_name = MACHINES.get(machine, {}).get('name', machine)
    
    conn = get_conn()
    cur = conn.cursor()
    
    # Get current task before completing
    cur.execute("SELECT current_task FROM loom_fleet_status WHERE machine_id = %s", (machine,))
    row = cur.fetchone()
    task = row[0] if row else 'Unknown task'
    
    # Mark complete
    cur.execute("""
    UPDATE loom_fleet_status 
    SET status = 'complete',
        completed_at = CURRENT_TIMESTAMP,
        last_heartbeat = CURRENT_TIMESTAMP,
        completion_summary = %s,
        current_step = 'DONE'
    WHERE machine_id = %s
    """, (summary, machine))
    
    # Log completion event
    cur.execute("""
    INSERT INTO loom_fleet_log (machine_id, event_type, message, task)
    VALUES (%s, 'complete', %s, %s)
    """, (machine, summary, task))
    
    # Also complete any pending instructions for this machine/task
    cur.execute("""
    UPDATE loom_fleet_instructions 
    SET status = 'complete', completed_at = CURRENT_TIMESTAMP, result_summary = %s
    WHERE to_machine = %s AND status = 'accepted' AND task_name ILIKE %s
    """, (summary, machine, f"%{task}%"))
    
    conn.commit()
    conn.close()
    
    print(f"[{machine_name}] COMPLETE: {task}")
    print(f"  Summary: {summary}")


def show_status():
    """Check in on all machines. Run from anywhere."""
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("""
    SELECT machine_id, machine_name, current_task, current_step,
           step_number, total_steps, status, last_heartbeat,
           started_at, completed_at, completion_summary
    FROM loom_fleet_status
    ORDER BY last_heartbeat DESC
    """)
    
    rows = cur.fetchall()
    
    # Also get pending instructions
    cur.execute("""
    SELECT to_machine, task_name, status, ts
    FROM loom_fleet_instructions
    WHERE status IN ('pending', 'accepted')
    ORDER BY ts DESC
    """)
    instructions = cur.fetchall()
    
    conn.close()
    
    now = datetime.now(timezone.utc)
    
    print("=" * 60)
    print(f"  LOOM FLEET STATUS")
    print(f"  {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)
    
    if not rows:
        print("\n  No fleet data yet. Machines will appear as they report in.\n")
        return
    
    for row in rows:
        mid, name, task, step, step_num, total, status, heartbeat, started, completed, summary = row
        
        # Calculate time since last heartbeat
        if heartbeat:
            delta = now - heartbeat.replace(tzinfo=timezone.utc) if heartbeat.tzinfo is None else now - heartbeat
            if delta.total_seconds() < 60:
                ago = f"{int(delta.total_seconds())}s ago"
            elif delta.total_seconds() < 3600:
                ago = f"{int(delta.total_seconds() / 60)}m ago"
            else:
                ago = f"{int(delta.total_seconds() / 3600)}h ago"
        else:
            ago = "unknown"
        
        # Status indicator
        if status == 'complete':
            icon = "[DONE]"
        elif delta.total_seconds() > 600:  # >10 min = possibly stale
            icon = "[STALE?]"
        else:
            icon = "[ACTIVE]"
        
        # Step progress
        step_str = ""
        if total and total > 0:
            step_str = f" Step {step_num}/{total}"
        
        name_str = f"{name} ({mid})"
        print(f"\n  {icon} {name_str:20s} | {ago:>8s}")
        if task:
            print(f"         Task: {task}{step_str}")
        if step and step != 'DONE':
            print(f"         Now:  {step}")
        if status == 'complete' and summary:
            print(f"         Result: {summary}")
    
    # Show pending instructions
    if instructions:
        print(f"\n{'=' * 60}")
        print("  PENDING INSTRUCTIONS")
        print(f"{'=' * 60}")
        for inst in instructions:
            to_m, task, st, ts = inst
            to_name = MACHINES.get(to_m, {}).get('name', to_m)
            icon = ">>>" if st == 'pending' else "..."
            print(f"  {icon} -> {to_name}: {task} ({st})")
    
    print()


def send_instructions(to_machine: str, task_name: str, instructions: str, 
                      total_steps: int = 1, from_machine: str = None):
    """Send instructions to a specific machine via LoomCloud."""
    if from_machine is None:
        from_machine = detect_machine()
    
    from_name = MACHINES.get(from_machine, {}).get('name', from_machine)
    to_name = MACHINES.get(to_machine, {}).get('name', to_machine)
    
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("""
    INSERT INTO loom_fleet_instructions 
        (from_machine, to_machine, task_name, instructions, total_steps)
    VALUES (%s, %s, %s, %s, %s)
    RETURNING id
    """, (from_machine, to_machine, task_name, instructions, total_steps))
    
    inst_id = cur.fetchone()[0]
    
    # Log it
    cur.execute("""
    INSERT INTO loom_fleet_log (machine_id, event_type, message, task)
    VALUES (%s, 'instruction_sent', %s, %s)
    """, (from_machine, f"Sent to {to_name}: {task_name}", task_name))
    
    conn.commit()
    conn.close()
    
    print(f"Instruction #{inst_id} sent: {from_name} -> {to_name}")
    print(f"  Task: {task_name}")
    print(f"  Steps: {total_steps}")
    print(f"  Target machine will see this on 'inbox' or 'recall'")


def check_inbox(machine: str = None):
    """Check for instructions waiting for this machine."""
    if machine is None:
        machine = detect_machine()
    
    machine_name = MACHINES.get(machine, {}).get('name', machine)
    
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("""
    SELECT id, from_machine, task_name, instructions, total_steps, ts, status
    FROM loom_fleet_instructions
    WHERE to_machine = %s AND status IN ('pending', 'accepted')
    ORDER BY ts DESC
    """, (machine,))
    
    rows = cur.fetchall()
    conn.close()
    
    if not rows:
        print(f"[{machine_name}] No pending instructions.")
        return
    
    print(f"{'=' * 60}")
    print(f"  INBOX for {machine_name}")
    print(f"{'=' * 60}")
    
    for row in rows:
        iid, from_m, task, inst, steps, ts, status = row
        from_name = MACHINES.get(from_m, {}).get('name', from_m)
        icon = "NEW >>>" if status == 'pending' else "IN PROGRESS"
        
        print(f"\n  [{icon}] Instruction #{iid} from {from_name}")
        print(f"  Task: {task} ({steps} steps)")
        print(f"  Sent: {ts.strftime('%Y-%m-%d %H:%M')}")
        print(f"  ---")
        # Print instructions with indent
        for line in inst.split('\n'):
            print(f"  {line}")
        
        if status == 'pending':
            print(f"\n  Accept with: python loom_fleet.py accept {iid}")
    
    print()


def accept_instruction(instruction_id: int, machine: str = None):
    """Mark an instruction as accepted (started working on it)."""
    if machine is None:
        machine = detect_machine()
    
    machine_name = MACHINES.get(machine, {}).get('name', machine)
    
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("""
    UPDATE loom_fleet_instructions 
    SET status = 'accepted', accepted_at = CURRENT_TIMESTAMP
    WHERE id = %s AND to_machine = %s
    RETURNING task_name, instructions, total_steps
    """, (instruction_id, machine))
    
    row = cur.fetchone()
    if row:
        task, inst, steps = row
        
        # Also set fleet status to this task
        cur.execute("""
        INSERT INTO loom_fleet_status 
            (machine_id, machine_name, current_task, current_step, 
             step_number, total_steps, status, last_heartbeat, started_at)
        VALUES (%s, %s, %s, 'Starting...', 0, %s, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (machine_id) DO UPDATE SET
            current_task = EXCLUDED.current_task,
            current_step = 'Starting...',
            step_number = 0,
            total_steps = EXCLUDED.total_steps,
            status = 'active',
            last_heartbeat = CURRENT_TIMESTAMP,
            started_at = CURRENT_TIMESTAMP,
            completed_at = NULL,
            completion_summary = NULL
        """, (machine, machine_name, task, steps))
        
        # Log acceptance
        cur.execute("""
        INSERT INTO loom_fleet_log (machine_id, event_type, message, task)
        VALUES (%s, 'instruction_accepted', %s, %s)
        """, (machine, f"Accepted instruction #{instruction_id}", task))
        
        conn.commit()
        conn.close()
        
        print(f"[{machine_name}] Accepted instruction #{instruction_id}: {task}")
        print(f"  Fleet status updated. {steps} steps to complete.")
        print(f"  Use 'python loom_fleet.py progress \"step description\"' as you work.")
    else:
        conn.close()
        print(f"No pending instruction #{instruction_id} for {machine_name}")


def show_log(machine: str = None, limit: int = 20):
    """Show recent fleet activity log."""
    conn = get_conn()
    cur = conn.cursor()
    
    if machine:
        cur.execute("""
        SELECT ts, machine_id, event_type, message, task
        FROM loom_fleet_log
        WHERE machine_id = %s
        ORDER BY ts DESC LIMIT %s
        """, (machine, limit))
    else:
        cur.execute("""
        SELECT ts, machine_id, event_type, message, task
        FROM loom_fleet_log
        ORDER BY ts DESC LIMIT %s
        """, (limit,))
    
    rows = cur.fetchall()
    conn.close()
    
    print(f"{'=' * 60}")
    print(f"  FLEET ACTIVITY LOG (last {limit})")
    print(f"{'=' * 60}")
    
    for row in rows:
        ts, mid, etype, msg, task = row
        name = MACHINES.get(mid, {}).get('name', mid)
        time_str = ts.strftime('%H:%M:%S') if ts else '??:??:??'
        print(f"  [{time_str}] {name:8s} | {etype:20s} | {msg[:60]}")
    
    print()


# --- CLI ---

def print_usage():
    print("""
LOOM FLEET SYNC - Coordinated Multi-Machine Awareness

Commands:
  update <task> <step> [--machine X] [--steps N]   Push current status
  progress <message> [--machine X]                  Log progress milestone
  complete <summary> [--machine X]                  Mark task complete
  status                                            Check all machines
  send <machine> <task> <instructions> [--steps N]  Send instructions
  inbox                                             Check your inbox
  accept <id>                                       Accept an instruction
  log [--machine X] [--limit N]                     Show activity log
  init                                              Create DB tables
""")


if __name__ == "__main__":
    args = sys.argv[1:]
    
    if not args:
        print_usage()
        sys.exit(0)
    
    cmd = args[0]
    
    # Parse --machine flag
    machine = None
    if '--machine' in args:
        idx = args.index('--machine')
        if idx + 1 < len(args):
            machine = args[idx + 1]
            args = args[:idx] + args[idx+2:]
    
    # Parse --steps flag
    steps = 0
    if '--steps' in args:
        idx = args.index('--steps')
        if idx + 1 < len(args):
            steps = int(args[idx + 1])
            args = args[:idx] + args[idx+2:]
    
    # Parse --limit flag
    limit = 20
    if '--limit' in args:
        idx = args.index('--limit')
        if idx + 1 < len(args):
            limit = int(args[idx + 1])
            args = args[:idx] + args[idx+2:]
    
    if cmd == 'init':
        init_tables()
    
    elif cmd == 'update' and len(args) >= 3:
        task = args[1]
        step = args[2]
        step_num = int(args[3]) if len(args) > 3 else 0
        update_status(task, step, machine=machine, step_num=step_num, total_steps=steps)
    
    elif cmd == 'progress' and len(args) >= 2:
        message = ' '.join(args[1:])
        log_progress(message, machine=machine)
    
    elif cmd == 'complete' and len(args) >= 2:
        summary = ' '.join(args[1:])
        mark_complete(summary, machine=machine)
    
    elif cmd == 'status':
        show_status()
    
    elif cmd == 'send' and len(args) >= 4:
        to_machine = args[1]
        task_name = args[2]
        instructions = args[3]
        send_instructions(to_machine, task_name, instructions, 
                         total_steps=steps or 1, from_machine=machine)
    
    elif cmd == 'inbox':
        check_inbox(machine=machine)
    
    elif cmd == 'accept' and len(args) >= 2:
        inst_id = int(args[1])
        accept_instruction(inst_id, machine=machine)
    
    elif cmd == 'log':
        show_log(machine=machine, limit=limit)
    
    else:
        print_usage()
