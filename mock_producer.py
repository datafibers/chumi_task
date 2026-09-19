"""
Mock Producer
Simulates a live chat stream by replaying chat_messages.jsonl one message at a time,
writing each to data/chat_stream.jsonl every INTERVAL_SECONDS.

Run in a separate terminal:
    python mock_producer.py
"""
import json
import time
import sys
from pathlib import Path

INTERVAL_SECONDS = 5
SOURCE_FILE = Path("data/chat_messages.jsonl")
STREAM_FILE = Path("data/chat_stream.jsonl")


def run():
    if not SOURCE_FILE.exists():
        print(f"Source file not found: {SOURCE_FILE}")
        sys.exit(1)

    messages = []
    with open(SOURCE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                messages.append(line)

    # Clear stream file at start
    STREAM_FILE.parent.mkdir(parents=True, exist_ok=True)
    STREAM_FILE.write_text("")

    print(f"[Producer] Starting stream: {len(messages)} messages, {INTERVAL_SECONDS}s interval")
    print(f"[Producer] Writing to: {STREAM_FILE}\n")

    for i, msg_line in enumerate(messages):
        msg = json.loads(msg_line)
        with open(STREAM_FILE, "a", encoding="utf-8") as f:
            f.write(msg_line + "\n")

        print(f"[Producer] [{i+1}/{len(messages)}] Sent msg {msg['msg_id']}: "
              f"{msg['user_id']}: {msg['text'][:60]}...")
        time.sleep(INTERVAL_SECONDS)

    print("\n[Producer] All messages sent. Stream complete.")


if __name__ == "__main__":
    run()
