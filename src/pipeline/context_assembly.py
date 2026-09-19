"""Build bounded contexts from reply threads and group-local activity."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Dict, List

from src.models import RawMessage


CONTEXT_INACTIVITY_SECONDS = 120


def build_reply_index(messages: List[RawMessage]) -> Dict[str, RawMessage]:
    return {message.msg_id: message for message in messages}


def resolve_thread(message: RawMessage, index: Dict[str, RawMessage]) -> List[RawMessage]:
    chain: List[RawMessage] = []
    current: RawMessage | None = message
    visited: set[str] = set()
    while current and current.msg_id not in visited:
        chain.append(current)
        visited.add(current.msg_id)
        current = index.get(current.reply_to) if current.reply_to else None
    return list(reversed(chain))


def _context_key(context: List[RawMessage]) -> str:
    return ",".join(sorted(message.msg_id for message in context))


def context_key(context: List[RawMessage]) -> str:
    """Stable key used to avoid processing the same context twice."""
    return _context_key(context)


def assemble_contexts(messages: List[RawMessage], inactivity_seconds: int | None = None) -> List[List[RawMessage]]:
    if not messages:
        return []

    ordered = sorted(messages, key=lambda message: (message.event_time, message.msg_id))
    index = build_reply_index(ordered)
    assigned: set[str] = set()
    contexts: List[List[RawMessage]] = []

    # A reply chain is a stronger boundary than a time window. Build from
    # roots so a three-message chain is not split when the last reply is seen.
    children: Dict[str, List[RawMessage]] = defaultdict(list)
    for message in ordered:
        if message.reply_to and message.reply_to in index:
            children[message.reply_to].append(message)
    roots = [message for message in ordered if not message.reply_to or message.reply_to not in index]
    for root in roots:
        if root.msg_id in assigned or root.msg_id not in children:
            continue
        thread: List[RawMessage] = []
        queue = [root]
        while queue:
            current = queue.pop(0)
            thread.append(current)
            queue.extend(sorted(children.get(current.msg_id, []), key=lambda item: (item.event_time, item.msg_id)))
        contexts.append(sorted(thread, key=lambda item: (item.event_time, item.msg_id)))
        assigned.update(item.msg_id for item in thread)

    # For messages without a usable reply, group by group and inactivity gap.
    by_group: Dict[str, List[RawMessage]] = defaultdict(list)
    for message in ordered:
        if message.msg_id not in assigned:
            by_group[message.group_id].append(message)

    window = timedelta(seconds=inactivity_seconds if inactivity_seconds is not None else CONTEXT_INACTIVITY_SECONDS)
    for group_messages in by_group.values():
        current: List[RawMessage] = []
        for message in group_messages:
            if not current or message.event_time - current[-1].event_time <= window:
                current.append(message)
                continue
            contexts.append(current)
            assigned.update(item.msg_id for item in current)
            current = [message]
        if current:
            contexts.append(current)
            assigned.update(item.msg_id for item in current)

    return sorted(contexts, key=lambda context: context[0].event_time)


def format_context_for_llm(context: List[RawMessage]) -> str:
    lines = ["<chat_context>"]
    for message in sorted(context, key=lambda item: item.event_time):
        reply_note = f" reply_to={message.reply_to}" if message.reply_to else ""
        lines.append(
            f"message_id={message.msg_id} time={message.timestamp} "
            f"group={message.group_id} user={message.user_id}{reply_note}: {message.text}"
        )
    lines.append("</chat_context>")
    return "\n".join(lines)
