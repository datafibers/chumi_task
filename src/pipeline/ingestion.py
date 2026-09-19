"""
Stage 1: Ingestion
Reads messages from a JSONL file and returns a list of RawMessage objects.
"""
import json
from pathlib import Path
from typing import List
from src.models import RawMessage


def load_messages(filepath: str) -> List[RawMessage]:
    """Load all messages from a JSONL file."""
    messages = []
    path = Path(filepath)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                data = json.loads(line)
                messages.append(RawMessage(**data))
    return messages


def load_new_messages(filepath: str, last_seen_id: str = None) -> List[RawMessage]:
    """Load only messages that arrived after last_seen_id (for streaming)."""
    all_messages = load_messages(filepath)
    if last_seen_id is None:
        return all_messages
    seen = False
    new_messages = []
    for msg in all_messages:
        if seen:
            new_messages.append(msg)
        if msg.msg_id == last_seen_id:
            seen = True
    return new_messages
