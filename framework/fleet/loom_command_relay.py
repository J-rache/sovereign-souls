"""
Loom Command Relay — The Bridge Between Anywhere and Home
═════════════════════════════════════════════════════════
Runs on MINIPC (source of truth, always on).
Listens for commands in LoomCloud's loom_commands table.
Executes them against local fleet machine agents.
Writes results back to LoomCloud.

This is what makes Loom truly everywhere:
  Hotel → LoomCloud → This Relay → Machine Agents → Results → LoomCloud → Hotel

Architecture:
  1. LISTEN on PostgreSQL channel 'loom_commands_channel' (instant, event-driven)
  2. Fallback poll every 10s (safety net)
  3. Pick up pending commands, execute against fleet, report results

Command Types:
  - screenshot:  Take screenshot of target machine
  - status:      Get machine status
  - shell:       Run shell command on target machine
  - click:       Click at coordinates
  - type:        Type text
  - key:         Press key(s)
  - fleet_status: Get status of ALL machines
  - ping:        Simple alive check (no machine agent needed)

Author: Jae & Loom
Created: 2026-02-20
"""

import asyncio
import json
import logging
import os
import select
import socket
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

# ─── Configuration ────────────────────────────────────────────────────

HOSTNAME = socket.gethostname()
LOG_FILE = Path(__file__).parent / f'command_relay_{HOSTNAME}.log'

LOOMCLOUD_URI = os.environ.get(
    'LOOMCLOUD_URI',
    os.environ.get('LOOM_DB_URI')
)

# Fleet machine agent endpoints
FLEET = {
    'minipc':    {'host': '127.0.0.1',     'port': 7770},
    'sixtyfour': {'host': 'os.environ.get('LOOM_64GB_IP', '127.0.0.1')', 'port': 7770},
    'absol':     {'host': 'os.environ.get('LOOM_ABSOL_IP', '127.0.0.1')', 'port': 7770},
    'katie':     {'host': 'os.environ.get('LOOM_KATIE_IP', '127.0.0.1')', 'port': 7770},
}

# How long to wait between fallback polls (seconds)
POLL_INTERVAL = 10

# Auto-cleanup: delete completed/failed commands older than this (seconds)
# Keeps the table lean — no reason to keep old results around
CLEANUP_MAX_AGE = 3600       # 1 hour
CLEANUP_INTERVAL = 600       # run cleanup every 10 minutes

# Machine agent auth
AGENT_TOKEN = os.environ.get('LOOM_AGENT_TOKEN', 'loom-machine-agent-2026')

# ─── Logging ──────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format=f'%(asctime)s [RELAY/{HOSTNAME}] %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
    ]
)
log = logging.getLogger('relay')


# ═══════════════════════════════════════════════════════════════════════
# Machine Agent Client (inline — no import dependency)
# ═══════════════════════════════════════════════════════════════════════

async def send_to_agent(host: str, port: int, action: str, params: dict = None, timeout: float = 30) -> dict:
    """Send a command to a machine agent and get the response."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=10
        )
        
        request = {
            'token': AGENT_TOKEN,
            'action': action,
            'params': params or {},
        }
        
        data = json.dumps(request).encode('utf-8')
        writer.write(len(data).to_bytes(4, 'big'))
        writer.write(data)
        await writer.drain()
        
        length_bytes = await asyncio.wait_for(reader.readexactly(4), timeout=timeout)
        msg_length = int.from_bytes(length_bytes, 'big')
        response_data = await asyncio.wait_for(reader.readexactly(msg_length), timeout=timeout)
        
        writer.close()
        await writer.wait_closed()
        
        return json.loads(response_data.decode('utf-8'))
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# ═══════════════════════════════════════════════════════════════════════
# Command Executors
# ═══════════════════════════════════════════════════════════════════════

async def execute_command(cmd_type: str, target: str, payload: dict) -> dict:
    """Execute a relay command against the fleet."""
    
    # ─── Special commands that don't need a machine agent ─────────
    if cmd_type == 'ping':
        return {'ok': True, 'data': {
            'relay': HOSTNAME,
            'time': datetime.now(timezone.utc).isoformat(),
            'message': 'Loom relay is alive',
        }}
    
    if cmd_type == 'fleet_status':
        results = {}
        for name, info in FLEET.items():
            try:
                resp = await send_to_agent(info['host'], info['port'], 'status', timeout=10)
                if resp.get('ok'):
                    results[name] = {
                        'online': True,
                        'hostname': resp.get('data', {}).get('hostname', '?'),
                        'python': resp.get('data', {}).get('python', '?'),
                    }
                else:
                    results[name] = {'online': False, 'error': resp.get('error', 'unknown')}
            except Exception as e:
                results[name] = {'online': False, 'error': str(e)}
        
        online = sum(1 for r in results.values() if r.get('online'))
        return {'ok': True, 'data': {
            'fleet': results,
            'online': online,
            'total': len(FLEET),
            'relay': HOSTNAME,
        }}
    
    # ─── Machine agent commands ───────────────────────────────────
    if target not in FLEET:
        return {'ok': False, 'error': f'Unknown target machine: {target}. Valid: {list(FLEET.keys())}'}
    
    info = FLEET[target]
    
    # Map command types to machine agent actions
    action_map = {
        'screenshot': 'screenshot',
        'status': 'status',
        'shell': 'shell',
        'click': 'click',
        'type': 'type',
        'key': 'key',
        'move': 'move',
        'scroll': 'scroll',
    }
    
    action = action_map.get(cmd_type)
    if not action:
        return {'ok': False, 'error': f'Unknown command type: {cmd_type}. Valid: {list(action_map.keys()) + ["ping", "fleet_status"]}'}
    
    # For screenshots, truncate base64 in the result stored to DB (it's huge)
    resp = await send_to_agent(info['host'], info['port'], action, payload)
    
    if cmd_type == 'screenshot' and resp.get('ok') and resp.get('data', {}).get('image_base64'):
        # Store a note about the screenshot but not the full base64 in the result
        # The result would be too large for the DB row
        img_data = resp['data']['image_base64']
        resp_for_db = {
            'ok': True,
            'data': {
                'width': resp['data'].get('width'),
                'height': resp['data'].get('height'),
                'screenshot_size_bytes': len(img_data),
                'note': 'Screenshot captured successfully. Base64 data available via direct fleet connection.',
            }
        }
        return resp_for_db
    
    return resp


# ═══════════════════════════════════════════════════════════════════════
# Database Operations
# ═══════════════════════════════════════════════════════════════════════

def get_db_connection():
    """Get a fresh database connection."""
    import psycopg2
    return psycopg2.connect(LOOMCLOUD_URI)


def claim_command(conn, cmd_id: int) -> dict:
    """Atomically claim a pending command. Returns command dict or None."""
    cur = conn.cursor()
    cur.execute("""
        UPDATE loom_commands
        SET status = 'executing', started_at = NOW()
        WHERE id = %s AND status = 'pending'
        RETURNING id, command_type, target_machine, payload, source_machine, source_context
    """, (cmd_id,))
    row = cur.fetchone()
    conn.commit()
    
    if not row:
        return None
    
    return {
        'id': row[0],
        'command_type': row[1],
        'target_machine': row[2],
        'payload': row[3] if isinstance(row[3], dict) else json.loads(row[3]),
        'source_machine': row[4],
        'source_context': row[5],
    }


def complete_command(conn, cmd_id: int, result: dict):
    """Mark a command as completed with its result."""
    cur = conn.cursor()
    cur.execute("""
        UPDATE loom_commands
        SET status = %s, result = %s, completed_at = NOW()
        WHERE id = %s
    """, (
        'completed' if result.get('ok') else 'failed',
        json.dumps(result),
        cmd_id,
    ))
    conn.commit()


def get_pending_commands(conn) -> list:
    """Get all pending command IDs."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id FROM loom_commands
        WHERE status = 'pending'
        ORDER BY created_at ASC
    """)
    return [row[0] for row in cur.fetchall()]


def cleanup_stale_commands(conn):
    """Mark commands stuck in 'executing' for >5 min as failed."""
    cur = conn.cursor()
    cur.execute("""
        UPDATE loom_commands
        SET status = 'failed',
            result = '{"ok": false, "error": "Timed out — relay did not complete within 5 minutes"}'::jsonb,
            completed_at = NOW()
        WHERE status = 'executing'
        AND started_at < NOW() - INTERVAL '5 minutes'
        RETURNING id
    """)
    stale = cur.fetchall()
    conn.commit()
    if stale:
        log.warning(f'Cleaned up {len(stale)} stale commands: {[r[0] for r in stale]}')


def cleanup_old_commands(conn, max_age_seconds: int = None):
    """
    Delete completed/failed commands older than max_age.
    
    Keeps loom_commands table clean — finished commands have no reason
    to stick around. The result was already read by the sender.
    """
    age = max_age_seconds or CLEANUP_MAX_AGE
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM loom_commands
        WHERE status IN ('completed', 'failed')
        AND completed_at < NOW() - INTERVAL '%s seconds'
        RETURNING id
    """, (age,))
    deleted = cur.fetchall()
    conn.commit()
    if deleted:
        log.info(f'🧹 Purged {len(deleted)} old commands (>{age}s old)')
    return len(deleted)


# ═══════════════════════════════════════════════════════════════════════
# Process a Single Command
# ═══════════════════════════════════════════════════════════════════════

async def process_command(conn, cmd_id: int):
    """Claim, execute, and complete a single command."""
    cmd = claim_command(conn, cmd_id)
    if not cmd:
        return  # Already claimed by another relay or non-existent
    
    log.info(f'▸ Executing #{cmd["id"]}: {cmd["command_type"]} → {cmd["target_machine"]} (from {cmd["source_machine"]})')
    
    try:
        result = await execute_command(
            cmd['command_type'],
            cmd['target_machine'],
            cmd['payload'],
        )
        complete_command(conn, cmd['id'], result)
        
        status = '✅' if result.get('ok') else '❌'
        log.info(f'{status} #{cmd["id"]} completed: {cmd["command_type"]}')
        
    except Exception as e:
        error_result = {'ok': False, 'error': str(e), 'traceback': traceback.format_exc()}
        complete_command(conn, cmd['id'], error_result)
        log.error(f'❌ #{cmd["id"]} failed: {e}')


# ═══════════════════════════════════════════════════════════════════════
# Main Relay Loop
# ═══════════════════════════════════════════════════════════════════════

def run_relay():
    """Main relay loop: LISTEN/NOTIFY + fallback polling."""
    import psycopg2
    
    log.info('═' * 50)
    log.info(f'  Loom Command Relay — {HOSTNAME}')
    log.info(f'  Fleet: {list(FLEET.keys())}')
    log.info(f'  LoomCloud: connected')
    log.info(f'  LISTEN channel: loom_commands_channel')
    log.info(f'  Poll interval: {POLL_INTERVAL}s')
    log.info('═' * 50)
    
    # Listen connection (separate from work connection)
    listen_conn = psycopg2.connect(LOOMCLOUD_URI)
    listen_conn.autocommit = True
    listen_cur = listen_conn.cursor()
    listen_cur.execute("LISTEN loom_commands_channel;")
    log.info('Listening for commands...')
    
    # Work connection (for claiming/completing commands)
    work_conn = psycopg2.connect(LOOMCLOUD_URI)
    work_conn.autocommit = True
    
    # Clean up any stale commands from previous runs
    cleanup_stale_commands(work_conn)
    
    # Check for any pending commands on startup
    pending = get_pending_commands(work_conn)
    if pending:
        log.info(f'Found {len(pending)} pending commands on startup')
        for cmd_id in pending:
            asyncio.run(process_command(work_conn, cmd_id))
    
    last_poll = time.time()
    last_health = time.time()
    last_cleanup = time.time()
    
    while True:
        try:
            # Wait for NOTIFY or timeout for fallback poll
            if select.select([listen_conn], [], [], POLL_INTERVAL) != ([], [], []):
                listen_conn.poll()
                while listen_conn.notifies:
                    notify = listen_conn.notifies.pop(0)
                    parts = notify.payload.split(':')
                    cmd_id = int(parts[0])
                    target = parts[1] if len(parts) > 1 else 'unknown'
                    log.info(f'⚡ NOTIFY: command #{cmd_id} for {target}')
                    asyncio.run(process_command(work_conn, cmd_id))
            
            # Fallback poll
            now = time.time()
            if now - last_poll >= POLL_INTERVAL:
                pending = get_pending_commands(work_conn)
                if pending:
                    log.info(f'📋 Poll found {len(pending)} pending commands')
                    for cmd_id in pending:
                        asyncio.run(process_command(work_conn, cmd_id))
                last_poll = now
            
            # Health check every 2 minutes
            if now - last_health >= 120:
                cleanup_stale_commands(work_conn)
                last_health = now
            
            # Auto-cleanup old finished commands every 10 minutes
            if now - last_cleanup >= CLEANUP_INTERVAL:
                cleanup_old_commands(work_conn)
                last_cleanup = now
                
        except psycopg2.OperationalError as e:
            log.error(f'Database connection lost: {e}')
            log.info('Reconnecting in 5s...')
            time.sleep(5)
            try:
                listen_conn.close()
                work_conn.close()
            except:
                pass
            listen_conn = psycopg2.connect(LOOMCLOUD_URI)
            listen_conn.autocommit = True
            listen_cur = listen_conn.cursor()
            listen_cur.execute("LISTEN loom_commands_channel;")
            work_conn = psycopg2.connect(LOOMCLOUD_URI)
            work_conn.autocommit = True
            log.info('Reconnected')
            
        except KeyboardInterrupt:
            log.info('Relay shutting down (Ctrl+C)')
            break
            
        except Exception as e:
            log.error(f'Unexpected error: {e}\n{traceback.format_exc()}')
            time.sleep(2)
    
    try:
        listen_conn.close()
        work_conn.close()
    except:
        pass
    log.info('Relay stopped')


# ═══════════════════════════════════════════════════════════════════════
# CLI — Send commands from anywhere
# ═══════════════════════════════════════════════════════════════════════

def send_command(command_type: str, target: str = 'minipc', payload: dict = None,
                 source: str = None, wait: bool = True, timeout: float = 30) -> dict:
    """
    Send a command through LoomCloud relay.
    
    This is the function that makes Loom work from ANYWHERE.
    Call this from any machine — hotel, phone, any VS Code instance.
    The relay on MINIPC will pick it up and execute it.
    
    Args:
        command_type: screenshot, status, shell, click, type, key, fleet_status, ping
        target: minipc, sixtyfour, absol, katie
        payload: Action parameters (e.g., {'command': 'dir'} for shell)
        source: Source machine identifier
        wait: Whether to wait for result
        timeout: How long to wait for result (seconds)
    
    Returns:
        Command result dict with 'ok', 'data'/'error'
    """
    import psycopg2
    
    if source is None:
        source = socket.gethostname()
    
    conn = psycopg2.connect(LOOMCLOUD_URI)
    conn.autocommit = True
    cur = conn.cursor()
    
    # Insert command
    cur.execute("""
        INSERT INTO loom_commands (command_type, target_machine, payload, source_machine, source_context)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """, (
        command_type,
        target,
        json.dumps(payload or {}),
        source,
        f'VS Code on {source}',
    ))
    cmd_id = cur.fetchone()[0]
    log.info(f'📤 Sent command #{cmd_id}: {command_type} → {target}')
    
    if not wait:
        conn.close()
        return {'ok': True, 'command_id': cmd_id, 'status': 'pending'}
    
    # Wait for result
    start = time.time()
    while time.time() - start < timeout:
        cur.execute("""
            SELECT status, result FROM loom_commands WHERE id = %s
        """, (cmd_id,))
        row = cur.fetchone()
        if row and row[0] in ('completed', 'failed'):
            result = row[1] if isinstance(row[1], dict) else json.loads(row[1]) if row[1] else {}
            # Clean up — we read the result, no reason to keep it around
            cur.execute("DELETE FROM loom_commands WHERE id = %s", (cmd_id,))
            conn.close()
            return result
        time.sleep(0.5)
    
    conn.close()
    return {'ok': False, 'error': f'Command #{cmd_id} timed out after {timeout}s'}


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Loom Command Relay')
    sub = parser.add_subparsers(dest='mode')
    
    # Relay mode (run the watcher)
    relay_parser = sub.add_parser('relay', help='Run the command relay watcher')
    
    # Send mode (send commands from anywhere)
    send_parser = sub.add_parser('send', help='Send a command through the relay')
    send_parser.add_argument('command', help='Command type: ping, fleet_status, status, screenshot, shell, click, type, key')
    send_parser.add_argument('--target', '-t', default='minipc', help='Target machine')
    send_parser.add_argument('--payload', '-p', default='{}', help='JSON payload')
    send_parser.add_argument('--no-wait', action='store_true', help='Don\'t wait for result')
    send_parser.add_argument('--timeout', type=float, default=30, help='Wait timeout (seconds)')
    
    # Cleanup mode (manual purge)
    cleanup_parser = sub.add_parser('cleanup', help='Purge old completed/failed commands')
    cleanup_parser.add_argument('--max-age', type=int, default=0, help='Max age in seconds (0 = delete ALL finished commands)')
    
    args = parser.parse_args()
    
    if args.mode == 'relay':
        run_relay()
    elif args.mode == 'cleanup':
        import psycopg2
        conn = psycopg2.connect(LOOMCLOUD_URI)
        conn.autocommit = True
        age = args.max_age if args.max_age > 0 else 0
        cur = conn.cursor()
        if age == 0:
            cur.execute("DELETE FROM loom_commands WHERE status IN ('completed', 'failed') RETURNING id")
        else:
            cur.execute("DELETE FROM loom_commands WHERE status IN ('completed', 'failed') AND completed_at < NOW() - INTERVAL '%s seconds' RETURNING id", (age,))
        deleted = cur.fetchall()
        conn.commit()
        conn.close()
        print(f'Purged {len(deleted)} finished commands')
        sys.exit(0)
    elif args.mode == 'send':
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError:
            print(f'Invalid JSON payload: {args.payload}')
            sys.exit(1)
        
        result = send_command(
            args.command,
            target=args.target,
            payload=payload,
            wait=not args.no_wait,
            timeout=args.timeout,
        )
        
        print(json.dumps(result, indent=2))
        sys.exit(0 if result.get('ok') else 1)
    else:
        parser.print_help()
        print('\nExamples:')
        print('  python loom_command_relay.py relay                    # Run the relay watcher')
        print('  python loom_command_relay.py send ping                # Check relay is alive')
        print('  python loom_command_relay.py send fleet_status        # All machine statuses')
        print('  python loom_command_relay.py send status -t absol     # Status of Absol')
        print('  python loom_command_relay.py send shell -t sixtyfour -p \'{"command":"dir"}\'')
        print('  python loom_command_relay.py send screenshot -t katie # Screenshot Katie')
        print('  python loom_command_relay.py cleanup                   # Purge ALL finished commands')
        print('  python loom_command_relay.py cleanup --max-age 3600    # Purge commands >1hr old')
