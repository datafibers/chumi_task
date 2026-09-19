"""
Stage 2: Context Assembly
Groups related messages into conversation contexts before sending to the LLM.

Two strategies:
  1. reply_to chain: follow explicit reply links to build a thread.
  2. time_window: group same user_id messages within TIME_WINDOW_SECONDS.
"""
from typing import List, Dict
from collections import defaultdict
from src.models import RawMessage
from datetime import datetime, timezone

TIME_WINDOW_SECONDS = 300  # 5 minutes


def build_reply_index(messages: List[RawMessage]) -> Dict[str, RawMessage]:
    """Index messages by msg_id for O(1) reply chain lookup."""
    return {m.msg_id: m for m in messages}


def resolve_thread(msg: RawMessage, index: Dict[str, RawMessage]) -> List[RawMessage]:
    """Follow reply_to chain upward and return ordered thread (oldest first)."""
    thread = []
    current = msg
    visited = set()
    while current and current.msg_id not in visited:
        thread.append(current)
        visited.add(current.msg_id)
        current = index.get(current.reply_to) if current.reply_to else None
    return list(reversed(thread))


def assemble_contexts(messages: List[RawMessage]) -> List[List[RawMessage]]:
    """
    Returns a list of contexts. Each context is a list of related RawMessages
    that should be sent together to the LLM for extraction.

    Priority:
    1. Messages with reply_to form explicit threads.
    2. Remaining messages are grouped by (user_id, group_id) within a time window.
    3. Single standalone messages form their own context.
    """
    index = build_reply_index(messages)
    contexts = []
    assigned = set()

    # Strategy 1: Build explicit reply threads
    # Find "leaf" messages (messages that are replied to but don't reply to anything themselves, or the top of a chain)
    reply_targets = {m.reply_to for m in messages if m.reply_to}
    
    for msg in messages:
        if msg.reply_to and msg.reply_to in index:
            # This message is part of a reply chain; build the full thread
            thread = resolve_thread(msg, index)
            thread_ids = {m.msg_id for m in thread}
            if not thread_ids.issubset(assigned):
                contexts.append(thread)
                assigned.update(thread_ids)

    # Strategy 2: Time-window grouping for same user/group
    unassigned = [m for m in messages if m.msg_id not in assigned]
    
    # Group by (user_id, group_id)
    user_groups: Dict[tuple, List[RawMessage]] = defaultdict(list)
    for msg in unassigned:
        user_groups[(msg.user_id, msg.group_id)].append(msg)

    for (user_id, group_id), user_msgs in user_groups.items():
        # Sort by timestamp
        user_msgs.sort(key=lambda m: m.timestamp)
        window = []
        for msg in user_msgs:
            if msg.msg_id in assigned:
                continue
            if not window:
                window.append(msg)
            else:
                last_ts = datetime.fromisoformat(window[-1].timestamp.replace("Z", "+00:00"))
                curr_ts = datetime.fromisoformat(msg.timestamp.replace("Z", "+00:00"))
                delta = (curr_ts - last_ts).total_seconds()
                if delta <= TIME_WINDOW_SECONDS:
                    window.append(msg)
                else:
                    # Flush current window
                    contexts.append(list(window))
                    assigned.update(m.msg_id for m in window)
                    window = [msg]
            assigned.add(msg.msg_id)
        if window:
            contexts.append(list(window))
            assigned.update(m.msg_id for m in window)

    # Strategy 3: Any remaining truly standalone messages
    for msg in messages:
        if msg.msg_id not in assigned:
            contexts.append([msg])

    return contexts


def format_context_for_llm(context: List[RawMessage]) -> str:
    """Format a context block as a readable string for the LLM prompt."""
    lines = []
    for msg in context:
        reply_note = f" [replying to {msg.reply_to}]" if msg.reply_to else ""
        lines.append(f"[{msg.timestamp}] {msg.user_id}{reply_note}: {msg.text}")
    return "\n".join(lines)
