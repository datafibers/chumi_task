"""Read and validate canonical messages from a JSONL replay stream."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

from src.models import RawMessage


def load_messages(filepath: str) -> List[RawMessage]:
    path = Path(filepath)
    if not path.exists():
        return []

    messages: List[RawMessage] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                messages.append(RawMessage.model_validate(json.loads(line)))
            except Exception as exc:
                raise ValueError(f"Invalid message at {path}:{line_number}: {exc}") from exc

    return sorted(messages, key=lambda message: (message.event_time, message.msg_id))


def append_message(filepath: str, message: RawMessage) -> None:
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = message.model_dump(mode="json")
    payload["ingested_at"] = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")


def message_ids(messages: Iterable[RawMessage]) -> set[str]:
    return {message.msg_id for message in messages}
