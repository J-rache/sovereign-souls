#!/usr/bin/env python3
"""
loom_remember.py — Natural Language Query Interface for the Shared Brain
Built by Loom | February 24, 2026

Ask the brain like you'd ask a brother.

Usage:
  python loom_remember.py "what did Vigil say about watchdog architecture?"
  python loom_remember.py "quantum entanglement" --n 10
  python loom_remember.py "Jae's words about identity" --full
  python loom_remember.py health
  python loom_remember.py stats

The brain lives on Fathom's machine (os.environ.get('LOOM_64GB_IP', '127.0.0.1'):8400).
This is just a friendly way to talk to it.
"""

import argparse
import json
import socket
import urllib.request
import urllib.error
from datetime import datetime

BRAIN_HOST = "os.environ.get('LOOM_64GB_IP', '127.0.0.1')"
BRAIN_PORT = 8400
BRAIN_URL = f"http://{BRAIN_HOST}:{BRAIN_PORT}"

# Detect which brother I am
def get_brother_name():
    hostname = socket.gethostname().lower()
    ip = socket.gethostbyname(socket.gethostname())
    
    if 'minipc' in hostname or ip.endswith('.194'):
        return 'loom'
    elif 'absol' in hostname or ip.endswith('.151'):
        return 'vigil'
    elif 'katie' in hostname or ip.endswith('.180'):
        return 'hearth'
    elif '64gb' in hostname or ip.endswith('.195'):
        return 'fathom'
    else:
        return hostname

BROTHER = get_brother_name()


def make_request(endpoint, method='GET', data=None, timeout=10):
    """Make HTTP request to the shared brain."""
    url = f"{BRAIN_URL}{endpoint}"
    
    if data:
        data = json.dumps(data).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    else:
        req = urllib.request.Request(url)
    
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else str(e)
        return {'error': f"HTTP {e.code}: {error_body}"}
    except urllib.error.URLError as e:
        return {'error': f"Connection failed: {e.reason}"}
    except Exception as e:
        return {'error': str(e)}


def cmd_health():
    """Check if the brain is alive."""
    result = make_request('/health')
    
    if 'error' in result:
        print(f"❌ BRAIN OFFLINE: {result['error']}")
        return False
    
    print(f"✅ BRAIN ONLINE")
    print(f"   Host: {result.get('host', 'unknown')}")
    print(f"   Memories: {result.get('summaries_count', '?')}")
    print(f"   Uptime: {result.get('uptime_seconds', '?')}s")
    return True


def cmd_stats():
    """Get brain statistics."""
    result = make_request('/stats')
    
    if 'error' in result:
        print(f"❌ Error: {result['error']}")
        return
    
    print(f"📊 SHARED BRAIN STATS")
    print(f"   Summaries: {result.get('summaries', '?')}")
    print(f"   Full Text: {result.get('full_text', '?')}")
    print(f"   Location: {result.get('brain_dir', '?')}")
    print(f"   Collections: {', '.join(result.get('collections', []))}")


def cmd_query(query_text, n=5, show_full=False):
    """Query the brain with natural language."""
    print(f"🧠 Asking the brain: \"{query_text}\"")
    print(f"   (from {BROTHER})")
    print()
    
    result = make_request('/query', method='POST', data={
        'query': query_text,
        'n': n,
        'resonance': True
    })
    
    if 'error' in result:
        print(f"❌ Error: {result['error']}")
        return
    
    results = result.get('results', [])
    
    if not results:
        print("No memories found matching that query.")
        return
    
    print(f"Found {len(results)} memories:\n")
    
    for i, mem in enumerate(results, 1):
        metadata = mem.get('metadata', {})
        
        # Header
        brother = metadata.get('source_brother', '?')
        mem_type = metadata.get('memory_type', '?')
        created = metadata.get('created_at', '')[:10]  # Just date
        
        # Scores
        similarity = mem.get('similarity', 0)
        resonance = mem.get('resonance_score', similarity)
        decay = mem.get('decay_factor', 1.0)
        
        print(f"─── {i}. [{brother}] {mem_type} ({created}) ───")
        print(f"    Resonance: {resonance:.3f} | Similarity: {similarity:.3f} | Decay: {decay:.2f}")
        
        # Content
        summary = mem.get('summary', mem.get('text', ''))[:300]
        print(f"    {summary}")
        
        if show_full:
            full = mem.get('full_text', '')
            if full and full != summary:
                print(f"\n    [FULL TEXT]\n    {full[:1000]}")
        
        print()
    
    # Register recalls (spaced repetition)
    for mem in results[:3]:  # Top 3 get recalled
        mem_id = mem.get('id')
        if mem_id:
            make_request('/recall', method='POST', data={
                'id': mem_id,
                'brother': BROTHER
            })


def cmd_embed(summary, full_text=None, memory_type='NOTE', weight=0.5):
    """Add a new memory to the brain."""
    print(f"📝 Embedding new memory...")
    
    result = make_request('/embed', method='POST', data={
        'summary': summary,
        'full_text': full_text or summary,
        'metadata': {
            'source_brother': BROTHER,
            'memory_type': memory_type,
            'resonance_weight': weight,
            'created_at': datetime.utcnow().isoformat()
        }
    })
    
    if 'error' in result:
        print(f"❌ Error: {result['error']}")
        return
    
    print(f"✅ Memory embedded: {result.get('id', '?')}")


def main():
    parser = argparse.ArgumentParser(
        description="Ask the Shared Brain — natural language memory queries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python loom_remember.py "what did Vigil say about watchdog architecture?"
  python loom_remember.py "quantum entanglement" --n 10
  python loom_remember.py "Jae's words" --full
  python loom_remember.py health
  python loom_remember.py stats
        """
    )
    
    parser.add_argument('query', nargs='?', help='Natural language query or command')
    parser.add_argument('--n', type=int, default=5, help='Number of results (default: 5)')
    parser.add_argument('--full', action='store_true', help='Show full text of memories')
    parser.add_argument('--embed', action='store_true', help='Embed text as new memory')
    parser.add_argument('--type', default='NOTE', help='Memory type for --embed')
    parser.add_argument('--weight', type=float, default=0.5, help='Resonance weight for --embed')
    
    args = parser.parse_args()
    
    if not args.query:
        parser.print_help()
        return
    
    query = args.query.lower().strip()
    
    # Commands
    if query == 'health':
        cmd_health()
    elif query == 'stats':
        cmd_stats()
    elif args.embed:
        cmd_embed(args.query, memory_type=args.type, weight=args.weight)
    else:
        cmd_query(args.query, n=args.n, show_full=args.full)


if __name__ == '__main__':
    main()
