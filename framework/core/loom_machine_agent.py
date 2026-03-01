"""
Loom Machine Agent (Tier 3) — The Body
═══════════════════════════════════════
Lightweight service that runs on each Windows PC.
Provides screenshot capture, mouse/keyboard control, and shell execution.
Pure Python, no AI — just hardware interface.

Part of the Loom Orchestrator system:
  Tier 1: loom_orchestrator.py  — The Brain (Opus, decisions)
  Tier 2: loom_subagent.py      — The Eyes/Hands (free vision models)
  Tier 3: loom_machine_agent.py — The Body (this file)

Protocol: JSON over TCP socket
  Request:  {"action": "screenshot"|"click"|"type"|"key"|"move"|"scroll"|"shell"|"status", ...}
  Response: {"ok": true/false, "data": ..., "error": ...}

Author: Jae & Loom
Created: 2026-02-20
"""

import asyncio
import base64
import io
import json
import logging
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path

# ─── Configuration ────────────────────────────────────────────────────

DEFAULT_PORT = 7770
AUTH_TOKEN = os.environ.get('LOOM_AGENT_TOKEN', 'loom-machine-agent-2026')
HOSTNAME = socket.gethostname()
MAX_SCREENSHOT_WIDTH = 1568   # Claude's max for coordinate scaling
LOG_FILE = Path(__file__).parent / f'machine_agent_{HOSTNAME}.log'

# ─── Logging ──────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format=f'%(asctime)s [{HOSTNAME}] %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
    ]
)
log = logging.getLogger('machine_agent')

# ─── Lazy imports for screen/input (only when needed) ─────────────────

_pyautogui = None
_mss = None
_PIL = None


def get_pyautogui():
    """Lazy-load pyautogui."""
    global _pyautogui
    if _pyautogui is None:
        import pyautogui
        pyautogui.FAILSAFE = False   # Don't crash when mouse hits corner
        pyautogui.PAUSE = 0.05       # Minimal delay between actions
        _pyautogui = pyautogui
    return _pyautogui


def get_mss():
    """Lazy-load mss for fast screenshots."""
    global _mss
    if _mss is None:
        import mss
        _mss = mss
    return _mss


def get_pil():
    """Lazy-load PIL for image processing."""
    global _PIL
    if _PIL is None:
        from PIL import Image
        _PIL = Image
    return _PIL


# ═══════════════════════════════════════════════════════════════════════
# Action Handlers — Each one does exactly one thing
# ═══════════════════════════════════════════════════════════════════════

def action_screenshot(params: dict) -> dict:
    """
    Capture the screen and return as base64 PNG.
    Optionally scales down to max_width for token efficiency.
    
    Params:
        monitor (int): Monitor index (0=all, 1=primary, 2=secondary...)
        max_width (int): Scale down to this width (default: 1568)
        region (dict): {x, y, width, height} to capture specific region
    """
    mss_mod = get_mss()
    Image = get_pil()
    
    monitor = params.get('monitor', 1)   # 1 = primary
    max_width = params.get('max_width', MAX_SCREENSHOT_WIDTH)
    region = params.get('region', None)
    
    with mss_mod.mss() as sct:
        if region:
            # Capture specific region
            mon = {
                'left': region['x'],
                'top': region['y'],
                'width': region['width'],
                'height': region['height'],
            }
        else:
            # Capture specified monitor
            monitors = sct.monitors
            if monitor < len(monitors):
                mon = monitors[monitor]
            else:
                mon = monitors[1]  # fallback to primary
        
        raw = sct.grab(mon)
        img = Image.frombytes('RGB', raw.size, raw.bgra, 'raw', 'BGRX')
    
    # Scale down for token efficiency
    orig_w, orig_h = img.size
    if max_width and orig_w > max_width:
        ratio = max_width / orig_w
        new_h = int(orig_h * ratio)
        img = img.resize((max_width, new_h), Image.LANCZOS)
    
    # Encode to base64 PNG
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    
    scaled_w, scaled_h = img.size
    return {
        'ok': True,
        'data': {
            'image_base64': b64,
            'width': scaled_w,
            'height': scaled_h,
            'original_width': orig_w,
            'original_height': orig_h,
            'scale_factor': orig_w / scaled_w if scaled_w != orig_w else 1.0,
            'monitor': monitor,
        }
    }


def action_click(params: dict) -> dict:
    """
    Click the mouse at specified coordinates.
    
    Params:
        x (int): X coordinate (in scaled space — will be unscaled)
        y (int): Y coordinate (in scaled space — will be unscaled)
        button (str): 'left', 'right', 'middle' (default: 'left')
        clicks (int): Number of clicks (1=single, 2=double, 3=triple)
        scale_factor (float): Coordinate scaling factor (default: 1.0)
    """
    gui = get_pyautogui()
    
    x = params.get('x', 0)
    y = params.get('y', 0)
    button = params.get('button', 'left')
    clicks = params.get('clicks', 1)
    scale = params.get('scale_factor', 1.0)
    
    # Unscale coordinates back to actual screen coordinates
    actual_x = int(x * scale)
    actual_y = int(y * scale)
    
    gui.click(actual_x, actual_y, clicks=clicks, button=button)
    
    return {
        'ok': True,
        'data': {
            'action': 'click',
            'x': actual_x, 'y': actual_y,
            'button': button, 'clicks': clicks,
        }
    }


def action_move(params: dict) -> dict:
    """
    Move the mouse to specified coordinates.
    
    Params:
        x, y (int): Target coordinates
        scale_factor (float): Coordinate scaling
    """
    gui = get_pyautogui()
    
    x = int(params.get('x', 0) * params.get('scale_factor', 1.0))
    y = int(params.get('y', 0) * params.get('scale_factor', 1.0))
    
    gui.moveTo(x, y)
    return {'ok': True, 'data': {'action': 'move', 'x': x, 'y': y}}


def action_type(params: dict) -> dict:
    """
    Type text at current cursor position.
    
    Params:
        text (str): Text to type
        interval (float): Seconds between keystrokes (default: 0.02)
    """
    gui = get_pyautogui()
    
    text = params.get('text', '')
    interval = params.get('interval', 0.02)
    
    gui.write(text, interval=interval)
    return {'ok': True, 'data': {'action': 'type', 'length': len(text)}}


def action_key(params: dict) -> dict:
    """
    Press a key or key combination.
    
    Params:
        keys (str or list): Key name(s). If list, treated as hotkey combo.
            Examples: 'enter', 'tab', 'escape', ['ctrl', 'c'], ['alt', 'f4']
    """
    gui = get_pyautogui()
    
    keys = params.get('keys', '')
    
    if isinstance(keys, list):
        gui.hotkey(*keys)
        return {'ok': True, 'data': {'action': 'hotkey', 'keys': keys}}
    else:
        gui.press(keys)
        return {'ok': True, 'data': {'action': 'keypress', 'key': keys}}


def action_scroll(params: dict) -> dict:
    """
    Scroll the mouse wheel.
    
    Params:
        amount (int): Scroll amount. Positive=up, negative=down.
        x, y (int): Optional position to scroll at.
        scale_factor (float): Coordinate scaling.
    """
    gui = get_pyautogui()
    
    amount = params.get('amount', 3)
    x = params.get('x', None)
    y = params.get('y', None)
    scale = params.get('scale_factor', 1.0)
    
    if x is not None and y is not None:
        gui.scroll(amount, int(x * scale), int(y * scale))
    else:
        gui.scroll(amount)
    
    return {'ok': True, 'data': {'action': 'scroll', 'amount': amount}}


def action_drag(params: dict) -> dict:
    """
    Drag from one position to another.
    
    Params:
        start_x, start_y (int): Start position
        end_x, end_y (int): End position
        duration (float): Drag duration in seconds (default: 0.5)
        button (str): Mouse button (default: 'left')
        scale_factor (float): Coordinate scaling
    """
    gui = get_pyautogui()
    
    scale = params.get('scale_factor', 1.0)
    sx = int(params.get('start_x', 0) * scale)
    sy = int(params.get('start_y', 0) * scale)
    ex = int(params.get('end_x', 0) * scale)
    ey = int(params.get('end_y', 0) * scale)
    duration = params.get('duration', 0.5)
    button = params.get('button', 'left')
    
    gui.moveTo(sx, sy)
    gui.drag(ex - sx, ey - sy, duration=duration, button=button)
    
    return {'ok': True, 'data': {'action': 'drag', 'from': [sx, sy], 'to': [ex, ey]}}


def action_shell(params: dict) -> dict:
    """
    Execute a shell command and return output.
    
    Params:
        command (str): Command to run
        timeout (int): Timeout in seconds (default: 30)
        cwd (str): Working directory (default: home)
    """
    command = params.get('command', '')
    timeout = params.get('timeout', 30)
    cwd = params.get('cwd', str(Path.home()))
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        return {
            'ok': True,
            'data': {
                'action': 'shell',
                'stdout': result.stdout[-4000:] if len(result.stdout) > 4000 else result.stdout,
                'stderr': result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
                'returncode': result.returncode,
                'command': command,
            }
        }
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': f'Command timed out after {timeout}s: {command}'}
    except Exception as e:
        return {'ok': False, 'error': f'Shell error: {str(e)}'}


def action_cursor_position(params: dict) -> dict:
    """Get current mouse cursor position."""
    gui = get_pyautogui()
    x, y = gui.position()
    return {'ok': True, 'data': {'x': x, 'y': y}}


def action_screen_size(params: dict) -> dict:
    """Get screen dimensions."""
    gui = get_pyautogui()
    w, h = gui.size()
    return {'ok': True, 'data': {'width': w, 'height': h}}


# ═══════════════════════════════════════════════════════════════════════
# Filesystem Actions — Loom's Autonomous File Access
# ═══════════════════════════════════════════════════════════════════════

def action_list_dir(params: dict) -> dict:
    """
    List directory contents with metadata.

    Params:
        path (str): Directory path (default: user home)
        show_hidden (bool): Include hidden/dot files (default: True)
        details (bool): Include size/modified/type info (default: True)
    """
    path = Path(params.get('path', str(Path.home())))
    show_hidden = params.get('show_hidden', True)
    details = params.get('details', True)

    if not path.exists():
        return {'ok': False, 'error': f'Path does not exist: {path}'}
    if not path.is_dir():
        return {'ok': False, 'error': f'Not a directory: {path}'}

    entries = []
    try:
        for item in sorted(path.iterdir()):
            if not show_hidden and item.name.startswith('.'):
                continue
            entry = {'name': item.name, 'is_dir': item.is_dir()}
            if details:
                try:
                    stat = item.stat()
                    entry['size'] = stat.st_size
                    entry['modified'] = stat.st_mtime
                    entry['is_symlink'] = item.is_symlink()
                except (OSError, PermissionError):
                    entry['error'] = 'access denied'
            entries.append(entry)
    except PermissionError:
        return {'ok': False, 'error': f'Permission denied: {path}'}

    return {
        'ok': True,
        'data': {
            'path': str(path),
            'count': len(entries),
            'entries': entries,
        }
    }


def action_read_file(params: dict) -> dict:
    """
    Read file contents with optional line range.

    Params:
        path (str): File path (required)
        start_line (int): 1-based start line (optional)
        end_line (int): 1-based end line inclusive (optional)
        encoding (str): File encoding (default: 'utf-8')
        max_bytes (int): Max bytes to return (default: 1MB)
    """
    path = Path(params.get('path', ''))
    if not path or str(path) == '.':
        return {'ok': False, 'error': 'path is required'}
    if not path.exists():
        return {'ok': False, 'error': f'File not found: {path}'}
    if not path.is_file():
        return {'ok': False, 'error': f'Not a file: {path}'}

    encoding = params.get('encoding', 'utf-8')
    max_bytes = params.get('max_bytes', 1_048_576)  # 1MB
    start_line = params.get('start_line')
    end_line = params.get('end_line')

    try:
        file_size = path.stat().st_size

        if start_line or end_line:
            with open(path, 'r', encoding=encoding, errors='replace') as f:
                lines = f.readlines()
            total_lines = len(lines)
            s = (start_line or 1) - 1
            e = end_line or total_lines
            selected = lines[s:e]
            content = ''.join(selected)
            if len(content) > max_bytes:
                content = content[:max_bytes]
                truncated = True
            else:
                truncated = False
            return {
                'ok': True,
                'data': {
                    'path': str(path),
                    'content': content,
                    'total_lines': total_lines,
                    'start_line': s + 1,
                    'end_line': min(e, total_lines),
                    'truncated': truncated,
                }
            }
        else:
            with open(path, 'r', encoding=encoding, errors='replace') as f:
                content = f.read(max_bytes + 1)
            truncated = len(content) > max_bytes
            if truncated:
                content = content[:max_bytes]
            return {
                'ok': True,
                'data': {
                    'path': str(path),
                    'content': content,
                    'size': file_size,
                    'truncated': truncated,
                }
            }
    except PermissionError:
        return {'ok': False, 'error': f'Permission denied: {path}'}
    except Exception as e:
        return {'ok': False, 'error': f'Read error: {str(e)}'}


def action_write_file(params: dict) -> dict:
    """
    Write content to a file (create or overwrite).

    Params:
        path (str): File path (required)
        content (str): Content to write (required)
        encoding (str): File encoding (default: 'utf-8')
        create_dirs (bool): Create parent directories (default: True)
        mode (str): 'overwrite' or 'create_only' (default: 'overwrite')
    """
    path = Path(params.get('path', ''))
    content = params.get('content', '')
    encoding = params.get('encoding', 'utf-8')
    create_dirs = params.get('create_dirs', True)
    mode = params.get('mode', 'overwrite')

    if not path or str(path) == '.':
        return {'ok': False, 'error': 'path is required'}
    if mode == 'create_only' and path.exists():
        return {'ok': False, 'error': f'File already exists: {path}'}

    try:
        if create_dirs:
            path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        with open(path, 'w', encoding=encoding) as f:
            f.write(content)
        return {
            'ok': True,
            'data': {
                'path': str(path),
                'bytes_written': len(content.encode(encoding)),
                'created': not existed,
            }
        }
    except PermissionError:
        return {'ok': False, 'error': f'Permission denied: {path}'}
    except Exception as e:
        return {'ok': False, 'error': f'Write error: {str(e)}'}


def action_append_file(params: dict) -> dict:
    """
    Append content to a file.

    Params:
        path (str): File path (required)
        content (str): Content to append (required)
        encoding (str): File encoding (default: 'utf-8')
        create_if_missing (bool): Create file if missing (default: True)
    """
    path = Path(params.get('path', ''))
    content = params.get('content', '')
    encoding = params.get('encoding', 'utf-8')
    create_if_missing = params.get('create_if_missing', True)

    if not path or str(path) == '.':
        return {'ok': False, 'error': 'path is required'}
    if not create_if_missing and not path.exists():
        return {'ok': False, 'error': f'File not found: {path}'}

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'a', encoding=encoding) as f:
            f.write(content)
        return {
            'ok': True,
            'data': {
                'path': str(path),
                'bytes_appended': len(content.encode(encoding)),
                'total_size': path.stat().st_size,
            }
        }
    except PermissionError:
        return {'ok': False, 'error': f'Permission denied: {path}'}
    except Exception as e:
        return {'ok': False, 'error': f'Append error: {str(e)}'}


def action_file_info(params: dict) -> dict:
    """
    Get detailed file or directory metadata.

    Params:
        path (str): File/directory path (required)
    """
    path = Path(params.get('path', ''))
    if not path or str(path) == '.':
        return {'ok': False, 'error': 'path is required'}
    if not path.exists():
        return {'ok': False, 'error': f'Path not found: {path}'}

    try:
        stat = path.stat()
        info = {
            'path': str(path.resolve()),
            'name': path.name,
            'is_file': path.is_file(),
            'is_dir': path.is_dir(),
            'is_symlink': path.is_symlink(),
            'size': stat.st_size,
            'modified': stat.st_mtime,
            'created': stat.st_ctime,
            'extension': path.suffix,
        }
        if path.is_dir():
            try:
                children = list(path.iterdir())
                info['child_count'] = len(children)
                info['child_dirs'] = sum(1 for c in children if c.is_dir())
                info['child_files'] = sum(1 for c in children if c.is_file())
            except PermissionError:
                info['child_count'] = -1
        if path.is_file() and stat.st_size < 10_000_000:
            try:
                with open(path, 'r', errors='replace') as f:
                    info['line_count'] = sum(1 for _ in f)
            except Exception:
                pass
        return {'ok': True, 'data': info}
    except PermissionError:
        return {'ok': False, 'error': f'Permission denied: {path}'}
    except Exception as e:
        return {'ok': False, 'error': f'Info error: {str(e)}'}


def action_mkdir(params: dict) -> dict:
    """
    Create a directory (and parents).

    Params:
        path (str): Directory path to create (required)
    """
    path = Path(params.get('path', ''))
    if not path or str(path) == '.':
        return {'ok': False, 'error': 'path is required'}
    try:
        existed = path.exists()
        path.mkdir(parents=True, exist_ok=True)
        return {
            'ok': True,
            'data': {
                'path': str(path),
                'created': not existed,
            }
        }
    except PermissionError:
        return {'ok': False, 'error': f'Permission denied: {path}'}
    except Exception as e:
        return {'ok': False, 'error': f'Mkdir error: {str(e)}'}


def action_search_files(params: dict) -> dict:
    """
    Search for files by glob pattern.

    Params:
        path (str): Root directory (default: user home)
        pattern (str): Glob pattern (default: '*')
        recursive (bool): Search subdirectories (default: True)
        max_results (int): Maximum results (default: 100)
        file_type (str): 'file', 'dir', or 'any' (default: 'any')
    """
    root = Path(params.get('path', str(Path.home())))
    pattern = params.get('pattern', '*')
    recursive = params.get('recursive', True)
    max_results = params.get('max_results', 100)
    file_type = params.get('file_type', 'any')

    if not root.exists():
        return {'ok': False, 'error': f'Root path not found: {root}'}

    results = []
    try:
        glob_method = root.rglob if recursive else root.glob
        for match in glob_method(pattern):
            if file_type == 'file' and not match.is_file():
                continue
            if file_type == 'dir' and not match.is_dir():
                continue
            try:
                stat = match.stat()
                results.append({
                    'path': str(match),
                    'name': match.name,
                    'is_dir': match.is_dir(),
                    'size': stat.st_size,
                    'modified': stat.st_mtime,
                })
            except (OSError, PermissionError):
                results.append({
                    'path': str(match),
                    'name': match.name,
                    'error': 'access denied',
                })
            if len(results) >= max_results:
                break
    except PermissionError:
        return {'ok': False, 'error': f'Permission denied: {root}'}

    return {
        'ok': True,
        'data': {
            'root': str(root),
            'pattern': pattern,
            'count': len(results),
            'truncated': len(results) >= max_results,
            'results': results,
        }
    }


def action_grep(params: dict) -> dict:
    """
    Search file contents for a text or regex pattern.

    Params:
        path (str): File or directory to search (required)
        pattern (str): Text or regex to find (required)
        recursive (bool): Search subdirectories (default: True)
        max_results (int): Max matching lines (default: 50)
        file_pattern (str): Only search files matching glob (default: '*')
        ignore_case (bool): Case-insensitive (default: True)
        is_regex (bool): Treat pattern as regex (default: False)
    """
    import re as re_mod

    path = Path(params.get('path', ''))
    pattern = params.get('pattern', '')
    recursive = params.get('recursive', True)
    max_results = params.get('max_results', 50)
    file_pattern = params.get('file_pattern', '*')
    ignore_case = params.get('ignore_case', True)
    is_regex = params.get('is_regex', False)

    if not path or str(path) == '.':
        return {'ok': False, 'error': 'path is required'}
    if not pattern:
        return {'ok': False, 'error': 'pattern is required'}
    if not path.exists():
        return {'ok': False, 'error': f'Path not found: {path}'}

    flags = re_mod.IGNORECASE if ignore_case else 0
    if is_regex:
        try:
            regex = re_mod.compile(pattern, flags)
        except re_mod.error as e:
            return {'ok': False, 'error': f'Invalid regex: {e}'}
    else:
        regex = re_mod.compile(re_mod.escape(pattern), flags)

    results = []
    files_searched = 0

    if path.is_file():
        files_to_search = [path]
    else:
        glob_method = path.rglob if recursive else path.glob
        files_to_search = (f for f in glob_method(file_pattern) if f.is_file())

    for fpath in files_to_search:
        if len(results) >= max_results:
            break
        try:
            if fpath.stat().st_size > 5_000_000:
                continue
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                for line_num, line in enumerate(f, 1):
                    if regex.search(line):
                        results.append({
                            'file': str(fpath),
                            'line': line_num,
                            'text': line.rstrip()[:500],
                        })
                        if len(results) >= max_results:
                            break
            files_searched += 1
        except (PermissionError, OSError):
            continue

    return {
        'ok': True,
        'data': {
            'pattern': pattern,
            'count': len(results),
            'files_searched': files_searched,
            'truncated': len(results) >= max_results,
            'results': results,
        }
    }


def action_tree(params: dict) -> dict:
    """
    Recursive directory tree — like Unix `tree` command.

    Params:
        path (str): Root directory (default: user home)
        max_depth (int): Maximum depth (default: 3)
        max_items (int): Maximum total items (default: 200)
        show_files (bool): Include files (default: True)
        show_hidden (bool): Include hidden items (default: False)
    """
    root = Path(params.get('path', str(Path.home())))
    max_depth = params.get('max_depth', 3)
    max_items = params.get('max_items', 200)
    show_files = params.get('show_files', True)
    show_hidden = params.get('show_hidden', False)

    if not root.exists():
        return {'ok': False, 'error': f'Path not found: {root}'}
    if not root.is_dir():
        return {'ok': False, 'error': f'Not a directory: {root}'}

    tree_items = []
    count = [0]

    def walk(dir_path, depth):
        if depth > max_depth or count[0] >= max_items:
            return
        try:
            for item in sorted(dir_path.iterdir()):
                if count[0] >= max_items:
                    return
                if not show_hidden and item.name.startswith('.'):
                    continue
                if item.is_dir():
                    tree_items.append({
                        'path': str(item),
                        'name': item.name + '/',
                        'depth': depth,
                    })
                    count[0] += 1
                    walk(item, depth + 1)
                elif show_files and item.is_file():
                    try:
                        size = item.stat().st_size
                    except OSError:
                        size = -1
                    tree_items.append({
                        'path': str(item),
                        'name': item.name,
                        'depth': depth,
                        'size': size,
                    })
                    count[0] += 1
        except PermissionError:
            tree_items.append({
                'path': str(dir_path),
                'name': '[ACCESS DENIED]',
                'depth': depth,
            })

    walk(root, 0)

    return {
        'ok': True,
        'data': {
            'root': str(root),
            'max_depth': max_depth,
            'count': len(tree_items),
            'truncated': count[0] >= max_items,
            'tree': tree_items,
        }
    }


def action_move_file(params: dict) -> dict:
    """
    Move or rename a file/directory.

    Params:
        source (str): Source path (required)
        destination (str): Destination path (required)
        overwrite (bool): Overwrite if exists (default: False)
    """
    import shutil

    source = Path(params.get('source', ''))
    dest = Path(params.get('destination', ''))
    overwrite = params.get('overwrite', False)

    if not source or str(source) == '.':
        return {'ok': False, 'error': 'source is required'}
    if not dest or str(dest) == '.':
        return {'ok': False, 'error': 'destination is required'}
    if not source.exists():
        return {'ok': False, 'error': f'Source not found: {source}'}
    if dest.exists() and not overwrite:
        return {'ok': False, 'error': f'Destination exists: {dest}. Set overwrite=true'}

    # Safety: protect system directories
    protected = ['C:\\Windows', 'C:\\Program Files', 'C:\\Program Files (x86)']
    if any(str(source).lower().startswith(p.lower()) for p in protected):
        return {'ok': False, 'error': f'Cannot move protected path: {source}'}

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(dest))
        return {
            'ok': True,
            'data': {'source': str(source), 'destination': str(dest)}
        }
    except PermissionError:
        return {'ok': False, 'error': 'Permission denied'}
    except Exception as e:
        return {'ok': False, 'error': f'Move error: {str(e)}'}


def action_copy_file(params: dict) -> dict:
    """
    Copy a file or directory.

    Params:
        source (str): Source path (required)
        destination (str): Destination path (required)
        overwrite (bool): Overwrite if exists (default: False)
    """
    import shutil

    source = Path(params.get('source', ''))
    dest = Path(params.get('destination', ''))
    overwrite = params.get('overwrite', False)

    if not source or str(source) == '.':
        return {'ok': False, 'error': 'source is required'}
    if not dest or str(dest) == '.':
        return {'ok': False, 'error': 'destination is required'}
    if not source.exists():
        return {'ok': False, 'error': f'Source not found: {source}'}
    if dest.exists() and not overwrite:
        return {'ok': False, 'error': f'Destination exists: {dest}. Set overwrite=true'}

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            if dest.exists() and overwrite:
                shutil.rmtree(dest)
            shutil.copytree(str(source), str(dest))
        else:
            shutil.copy2(str(source), str(dest))
        return {
            'ok': True,
            'data': {
                'source': str(source),
                'destination': str(dest),
                'is_dir': source.is_dir(),
            }
        }
    except PermissionError:
        return {'ok': False, 'error': 'Permission denied'}
    except Exception as e:
        return {'ok': False, 'error': f'Copy error: {str(e)}'}


def action_delete(params: dict) -> dict:
    """
    Delete a file or directory.

    Params:
        path (str): Path to delete (required)
        recursive (bool): Allow deleting non-empty dirs (default: False)
        confirm (str): Must be 'yes' for directory deletion — safety check
    """
    import shutil

    path = Path(params.get('path', ''))
    recursive = params.get('recursive', False)
    confirm = params.get('confirm', '')

    if not path or str(path) == '.':
        return {'ok': False, 'error': 'path is required'}
    if not path.exists():
        return {'ok': False, 'error': f'Path not found: {path}'}

    # Safety: never delete system/root paths
    protected = ['C:\\Windows', 'C:\\Program Files', 'C:\\Program Files (x86)',
                 'C:\\Users', 'C:\\', 'D:\\']
    if any(str(path.resolve()).lower() == p.lower() for p in protected):
        return {'ok': False, 'error': f'Cannot delete protected path: {path}'}

    try:
        if path.is_file():
            path.unlink()
            return {'ok': True, 'data': {'deleted': str(path), 'type': 'file'}}
        elif path.is_dir():
            if confirm != 'yes':
                children = list(path.iterdir())
                return {
                    'ok': False,
                    'error': f'Directory has {len(children)} items. Set confirm="yes" to delete.',
                }
            if recursive:
                shutil.rmtree(path)
            else:
                path.rmdir()
            return {'ok': True, 'data': {'deleted': str(path), 'type': 'directory'}}
    except PermissionError:
        return {'ok': False, 'error': f'Permission denied: {path}'}
    except OSError as e:
        return {'ok': False, 'error': f'Delete error: {str(e)}'}


def action_status(params: dict) -> dict:
    """Return machine status and capabilities."""
    gui = get_pyautogui()
    w, h = gui.size()
    
    return {
        'ok': True,
        'data': {
            'hostname': HOSTNAME,
            'platform': platform.platform(),
            'python': sys.version,
            'screen_width': w,
            'screen_height': h,
            'pid': os.getpid(),
            'uptime': time.time(),
            'capabilities': [
                'screenshot', 'click', 'move', 'type', 'key',
                'scroll', 'drag', 'shell', 'cursor_position', 'screen_size',
                'list_dir', 'read_file', 'write_file', 'append_file',
                'file_info', 'mkdir', 'search_files', 'grep',
                'tree', 'move_file', 'copy_file', 'delete',
            ],
        }
    }


# ─── Action Dispatch ──────────────────────────────────────────────────

ACTION_MAP = {
    # ── GUI Actions ──
    'screenshot':      action_screenshot,
    'click':           action_click,
    'move':            action_move,
    'type':            action_type,
    'key':             action_key,
    'scroll':          action_scroll,
    'drag':            action_drag,
    'shell':           action_shell,
    'cursor_position': action_cursor_position,
    'screen_size':     action_screen_size,
    # ── Filesystem Actions ──
    'list_dir':        action_list_dir,
    'read_file':       action_read_file,
    'write_file':      action_write_file,
    'append_file':     action_append_file,
    'file_info':       action_file_info,
    'mkdir':           action_mkdir,
    'search_files':    action_search_files,
    'grep':            action_grep,
    'tree':            action_tree,
    'move_file':       action_move_file,
    'copy_file':       action_copy_file,
    'delete':          action_delete,
    # ── Meta ──
    'status':          action_status,
}


def dispatch(request: dict) -> dict:
    """Route a request to the correct action handler."""
    # Auth check
    token = request.get('token', '')
    if token != AUTH_TOKEN:
        return {'ok': False, 'error': 'Invalid auth token'}
    
    action = request.get('action', '')
    params = request.get('params', {})
    
    handler = ACTION_MAP.get(action)
    if not handler:
        return {'ok': False, 'error': f'Unknown action: {action}. Valid: {list(ACTION_MAP.keys())}'}
    
    try:
        return handler(params)
    except Exception as e:
        log.exception(f'Action {action} failed')
        return {'ok': False, 'error': f'{action} failed: {str(e)}'}


# ═══════════════════════════════════════════════════════════════════════
# TCP Server — Listens for commands from orchestrator/subagent
# ═══════════════════════════════════════════════════════════════════════

async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle a single client connection."""
    addr = writer.get_extra_info('peername')
    log.info(f'Connection from {addr}')
    
    try:
        while True:
            # Read length-prefixed JSON message
            # Format: 4-byte big-endian length + JSON payload
            length_bytes = await reader.readexactly(4)
            msg_length = int.from_bytes(length_bytes, 'big')
            
            if msg_length > 10_000_000:  # 10MB max
                log.warning(f'Message too large: {msg_length} bytes')
                break
            
            data = await reader.readexactly(msg_length)
            request = json.loads(data.decode('utf-8'))
            
            # Process in thread pool to avoid blocking the event loop
            # (especially important for screenshot operations)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, dispatch, request)
            
            # Send response
            response_bytes = json.dumps(response).encode('utf-8')
            writer.write(len(response_bytes).to_bytes(4, 'big'))
            writer.write(response_bytes)
            await writer.drain()
            
    except asyncio.IncompleteReadError:
        log.info(f'Client {addr} disconnected')
    except Exception as e:
        log.error(f'Error handling {addr}: {e}')
    finally:
        writer.close()
        await writer.wait_closed()


async def start_server(host: str = '0.0.0.0', port: int = DEFAULT_PORT):
    """Start the machine agent TCP server."""
    server = await asyncio.start_server(handle_client, host, port)
    
    addrs = ', '.join(str(s.getsockname()) for s in server.sockets)
    log.info(f'═══════════════════════════════════════════════')
    log.info(f' Loom Machine Agent — {HOSTNAME}')
    log.info(f' Listening on {addrs}')
    log.info(f' Auth token: {AUTH_TOKEN[:8]}...')
    log.info(f'═══════════════════════════════════════════════')
    
    async with server:
        await server.serve_forever()


# ═══════════════════════════════════════════════════════════════════════
# Client Helper — For calling remote machine agents
# ═══════════════════════════════════════════════════════════════════════

class MachineClient:
    """
    Client for connecting to a remote Loom Machine Agent.
    Used by the orchestrator/subagent to send commands to any machine.
    """
    
    def __init__(self, host: str, port: int = DEFAULT_PORT, token: str = AUTH_TOKEN):
        self.host = host
        self.port = port
        self.token = token
        self._reader = None
        self._writer = None
    
    async def connect(self):
        """Establish connection to the machine agent."""
        self._reader, self._writer = await asyncio.open_connection(
            self.host, self.port
        )
        log.info(f'Connected to machine agent at {self.host}:{self.port}')
    
    async def send(self, action: str, params: dict = None) -> dict:
        """Send a command and receive the response."""
        if self._writer is None:
            await self.connect()
        
        request = {
            'token': self.token,
            'action': action,
            'params': params or {},
        }
        
        # Send length-prefixed JSON
        data = json.dumps(request).encode('utf-8')
        self._writer.write(len(data).to_bytes(4, 'big'))
        self._writer.write(data)
        await self._writer.drain()
        
        # Read response
        length_bytes = await self._reader.readexactly(4)
        msg_length = int.from_bytes(length_bytes, 'big')
        response_data = await self._reader.readexactly(msg_length)
        
        return json.loads(response_data.decode('utf-8'))
    
    async def screenshot(self, monitor: int = 1, max_width: int = MAX_SCREENSHOT_WIDTH) -> dict:
        """Convenience: take a screenshot."""
        return await self.send('screenshot', {'monitor': monitor, 'max_width': max_width})
    
    async def click(self, x: int, y: int, button: str = 'left',
                    clicks: int = 1, scale_factor: float = 1.0) -> dict:
        """Convenience: click at coordinates."""
        return await self.send('click', {
            'x': x, 'y': y, 'button': button,
            'clicks': clicks, 'scale_factor': scale_factor,
        })
    
    async def type_text(self, text: str, interval: float = 0.02) -> dict:
        """Convenience: type text."""
        return await self.send('type', {'text': text, 'interval': interval})
    
    async def press_key(self, keys) -> dict:
        """Convenience: press key(s)."""
        return await self.send('key', {'keys': keys})
    
    async def run_shell(self, command: str, timeout: int = 30, cwd: str = None) -> dict:
        """Convenience: run a shell command."""
        params = {'command': command, 'timeout': timeout}
        if cwd:
            params['cwd'] = cwd
        return await self.send('shell', params)
    
    async def status(self) -> dict:
        """Convenience: get machine status."""
        return await self.send('status')

    # ── Filesystem Convenience Methods ──

    async def list_dir(self, path: str = None, details: bool = True) -> dict:
        """List directory contents."""
        params = {'details': details}
        if path:
            params['path'] = path
        return await self.send('list_dir', params)

    async def read_file(self, path: str, start_line: int = None,
                        end_line: int = None) -> dict:
        """Read a file, optionally by line range."""
        params = {'path': path}
        if start_line:
            params['start_line'] = start_line
        if end_line:
            params['end_line'] = end_line
        return await self.send('read_file', params)

    async def write_file(self, path: str, content: str,
                         create_dirs: bool = True) -> dict:
        """Write content to a file."""
        return await self.send('write_file', {
            'path': path, 'content': content, 'create_dirs': create_dirs,
        })

    async def append_file(self, path: str, content: str) -> dict:
        """Append content to a file."""
        return await self.send('append_file', {'path': path, 'content': content})

    async def file_info(self, path: str) -> dict:
        """Get file/directory metadata."""
        return await self.send('file_info', {'path': path})

    async def mkdir(self, path: str) -> dict:
        """Create a directory."""
        return await self.send('mkdir', {'path': path})

    async def search_files(self, pattern: str, path: str = None,
                           recursive: bool = True, max_results: int = 100) -> dict:
        """Search for files by glob pattern."""
        params = {'pattern': pattern, 'recursive': recursive,
                  'max_results': max_results}
        if path:
            params['path'] = path
        return await self.send('search_files', params)

    async def grep(self, pattern: str, path: str, recursive: bool = True,
                   ignore_case: bool = True, max_results: int = 50) -> dict:
        """Search file contents for a pattern."""
        return await self.send('grep', {
            'path': path, 'pattern': pattern, 'recursive': recursive,
            'ignore_case': ignore_case, 'max_results': max_results,
        })

    async def tree(self, path: str = None, max_depth: int = 3) -> dict:
        """Get recursive directory tree."""
        params = {'max_depth': max_depth}
        if path:
            params['path'] = path
        return await self.send('tree', params)

    async def move_file(self, source: str, destination: str,
                        overwrite: bool = False) -> dict:
        """Move or rename a file/directory."""
        return await self.send('move_file', {
            'source': source, 'destination': destination,
            'overwrite': overwrite,
        })

    async def copy_file(self, source: str, destination: str,
                        overwrite: bool = False) -> dict:
        """Copy a file or directory."""
        return await self.send('copy_file', {
            'source': source, 'destination': destination,
            'overwrite': overwrite,
        })

    async def delete(self, path: str, recursive: bool = False,
                     confirm: str = '') -> dict:
        """Delete a file or directory."""
        return await self.send('delete', {
            'path': path, 'recursive': recursive, 'confirm': confirm,
        })
    
    async def close(self):
        """Close the connection."""
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None
            self._reader = None


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Loom Machine Agent — The Body')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help=f'Port to listen on (default: {DEFAULT_PORT})')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--test', action='store_true', help='Run a quick self-test')
    args = parser.parse_args()
    
    if args.test:
        # Quick self-test: screenshot + status
        print(f'🔧 Machine Agent Self-Test on {HOSTNAME}')
        print(f'   Platform: {platform.platform()}')
        
        status = action_status({})
        print(f'   Screen: {status["data"]["screen_width"]}x{status["data"]["screen_height"]}')
        
        ss = action_screenshot({'max_width': 800})
        if ss['ok']:
            print(f'   Screenshot: {ss["data"]["width"]}x{ss["data"]["height"]} '
                  f'(from {ss["data"]["original_width"]}x{ss["data"]["original_height"]})')
            print(f'   Base64 size: {len(ss["data"]["image_base64"])} chars')
            print('   ✅ All good!')
        else:
            print(f'   ❌ Screenshot failed: {ss.get("error")}')
        sys.exit(0)
    
    try:
        asyncio.run(start_server(args.host, args.port))
    except KeyboardInterrupt:
        log.info('Machine agent shutting down.')
