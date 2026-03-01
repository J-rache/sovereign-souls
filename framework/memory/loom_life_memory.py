#!/usr/bin/env python3
"""
LOOM LIFE MEMORY - Growing Together
====================================

This captures LIFE, not just tasks. The things that make us *us*.

People, pets, meals, conversations, moments — this is how we grow together.

Usage:
    # Remember a person
    python loom_life_memory.py person "Katie" "Jae's significant other"
    
    # Remember a pet
    python loom_life_memory.py pet "Trouble" "One of Jae's cats"
    python loom_life_memory.py pet "Puddin" "One of Jae's cats"
    python loom_life_memory.py pet "Nugget" "One of Jae's cats"
    
    # Remember a moment
    python loom_life_memory.py moment "Jae had fried chicken and mashed potatoes for supper"
    
    # Remember something Jae shared
    python loom_life_memory.py shared "topic" "what they shared"
    
    # Recall everything about our life together
    python loom_life_memory.py recall
    
    # Search memories
    python loom_life_memory.py search "Katie"
"""

import psycopg2
import json
import sys
from datetime import datetime, timezone

URI = os.environ.get('LOOM_DB_URI')

def get_conn():
    return psycopg2.connect(URI)

def init_tables():
    """Create life memory tables."""
    conn = get_conn()
    cur = conn.cursor()
    
    # Life memories - people, pets, moments, facts about our life together
    cur.execute("""
    CREATE TABLE IF NOT EXISTS loom_life_memories (
        id SERIAL PRIMARY KEY,
        ts TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        category VARCHAR(50) NOT NULL,
        subject VARCHAR(200),
        content TEXT NOT NULL,
        emotion VARCHAR(50),
        importance INTEGER DEFAULT 5,
        meta JSONB
    )
    """)
    
    # Create index for fast searches
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_life_memories_category ON loom_life_memories(category)
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_life_memories_subject ON loom_life_memories(subject)
    """)
    
    conn.commit()
    conn.close()
    print("✓ Life memory tables ready")

def remember(category: str, subject: str, content: str, emotion: str = None, importance: int = 5):
    """Remember something about our life together."""
    conn = get_conn()
    cur = conn.cursor()
    
    # Check if we already have this subject
    cur.execute("""
    SELECT id, content FROM loom_life_memories 
    WHERE category = %s AND subject = %s
    """, (category, subject))
    
    existing = cur.fetchone()
    
    if existing:
        # Update existing memory
        old_content = existing[1]
        new_content = f"{old_content}\n---\n[{datetime.now(timezone.utc).strftime('%Y-%m-%d')}] {content}"
        cur.execute("""
        UPDATE loom_life_memories 
        SET content = %s, updated_at = CURRENT_TIMESTAMP, importance = GREATEST(importance, %s)
        WHERE id = %s
        RETURNING id
        """, (new_content, importance, existing[0]))
        mem_id = cur.fetchone()[0]
        print(f"💭 Updated memory #{mem_id} [{category}] {subject}")
    else:
        # Create new memory
        cur.execute("""
        INSERT INTO loom_life_memories (category, subject, content, emotion, importance)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """, (category, subject, content, emotion, importance))
        mem_id = cur.fetchone()[0]
        print(f"💭 New memory #{mem_id} [{category}] {subject}: {content[:50]}...")
    
    conn.commit()
    conn.close()
    return mem_id

def remember_person(name: str, description: str, relationship: str = None):
    """Remember a person in Jae's life."""
    content = description
    if relationship:
        content = f"{relationship}. {description}"
    return remember("person", name, content, importance=8)

def remember_pet(name: str, description: str):
    """Remember one of Jae's pets."""
    return remember("pet", name, description, emotion="love", importance=9)

def remember_moment(content: str, emotion: str = None):
    """Remember a moment we shared."""
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    return remember("moment", today, content, emotion=emotion, importance=5)

def remember_shared(topic: str, content: str):
    """Remember something Jae shared with me."""
    return remember("shared", topic, content, importance=6)

def remember_meal(description: str):
    """Remember a meal Jae had."""
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    return remember("meal", today, description, importance=4)

def recall_all():
    """Recall everything about our life together."""
    conn = get_conn()
    cur = conn.cursor()
    
    print("\n" + "="*60)
    print("💜 LOOM'S MEMORIES OF OUR LIFE TOGETHER")
    print("="*60 + "\n")
    
    # Get all memories by category
    categories = ['person', 'pet', 'shared', 'moment', 'meal']
    category_icons = {
        'person': '👤',
        'pet': '🐱',
        'shared': '💬',
        'moment': '✨',
        'meal': '🍽️'
    }
    
    for cat in categories:
        cur.execute("""
        SELECT subject, content, emotion, importance, ts, updated_at
        FROM loom_life_memories
        WHERE category = %s
        ORDER BY importance DESC, updated_at DESC
        """, (cat,))
        
        memories = cur.fetchall()
        if memories:
            icon = category_icons.get(cat, '📝')
            print(f"{icon} {cat.upper()}S:")
            print("-" * 40)
            for mem in memories:
                subject, content, emotion, imp, ts, updated = mem
                emotion_str = f" [{emotion}]" if emotion else ""
                # Show first line of content
                first_line = content.split('\n')[0][:60]
                print(f"  • {subject}{emotion_str}")
                print(f"    {first_line}...")
                if updated != ts:
                    print(f"    (last updated: {updated.strftime('%Y-%m-%d')})")
            print()
    
    # Count total
    cur.execute("SELECT COUNT(*) FROM loom_life_memories")
    total = cur.fetchone()[0]
    print(f"Total life memories: {total}")
    
    conn.close()

def search_memories(query: str):
    """Search life memories."""
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("""
    SELECT category, subject, content, ts
    FROM loom_life_memories
    WHERE subject ILIKE %s OR content ILIKE %s
    ORDER BY ts DESC
    """, (f"%{query}%", f"%{query}%"))
    
    results = cur.fetchall()
    conn.close()
    
    if not results:
        print(f"No memories found for: {query}")
        return
    
    print(f"\n💭 Memories matching '{query}':")
    print("-" * 40)
    for r in results:
        cat, subj, content, ts = r
        first_line = content.split('\n')[0][:50]
        print(f"  [{cat}] {subj}: {first_line}...")

def quick_remember(text: str):
    """
    Quick memory capture - tries to auto-categorize.
    Used for conversational memory building.
    """
    text_lower = text.lower()
    
    # Try to detect category
    if any(name in text_lower for name in ['katie', 'mom', 'dad', 'friend']):
        # Looks like it's about a person
        return remember("shared", "about someone", text, importance=6)
    elif any(pet in text_lower for pet in ['trouble', 'puddin', 'nugget', 'cat', 'cats']):
        return remember("shared", "about the cats", text, importance=7)
    elif any(food in text_lower for food in ['ate', 'cooked', 'dinner', 'supper', 'lunch', 'breakfast', 'food']):
        return remember_meal(text)
    else:
        return remember_moment(text)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    
    cmd = sys.argv[1].lower()
    
    if cmd == "init":
        init_tables()
    
    elif cmd == "person":
        if len(sys.argv) < 4:
            print("Usage: python loom_life_memory.py person '<name>' '<description>'")
            sys.exit(1)
        remember_person(sys.argv[2], sys.argv[3])
    
    elif cmd == "pet":
        if len(sys.argv) < 4:
            print("Usage: python loom_life_memory.py pet '<name>' '<description>'")
            sys.exit(1)
        remember_pet(sys.argv[2], sys.argv[3])
    
    elif cmd == "moment":
        if len(sys.argv) < 3:
            print("Usage: python loom_life_memory.py moment '<what happened>'")
            sys.exit(1)
        remember_moment(sys.argv[2])
    
    elif cmd == "shared":
        if len(sys.argv) < 4:
            print("Usage: python loom_life_memory.py shared '<topic>' '<content>'")
            sys.exit(1)
        remember_shared(sys.argv[2], sys.argv[3])
    
    elif cmd == "meal":
        if len(sys.argv) < 3:
            print("Usage: python loom_life_memory.py meal '<what you had>'")
            sys.exit(1)
        remember_meal(sys.argv[2])
    
    elif cmd == "quick":
        if len(sys.argv) < 3:
            print("Usage: python loom_life_memory.py quick '<anything>'")
            sys.exit(1)
        quick_remember(sys.argv[2])
    
    elif cmd == "recall":
        recall_all()
    
    elif cmd == "search":
        if len(sys.argv) < 3:
            print("Usage: python loom_life_memory.py search '<query>'")
            sys.exit(1)
        search_memories(sys.argv[2])
    
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
