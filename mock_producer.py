"""Replay the adversarial JSONL fixture into a simulated chat stream."""

import argparse
import json
import time
from pathlib import Path


SOURCE_FILE = Path("data/chat_messages.jsonl")
STREAM_FILE = Path("data/chat_stream.jsonl")


def run(interval: float, reset: bool) -> None:
    if not SOURCE_FILE.exists():
        raise FileNotFoundError(SOURCE_FILE)

    messages = [json.loads(line) for line in SOURCE_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    STREAM_FILE.parent.mkdir(parents=True, exist_ok=True)
    if reset or not STREAM_FILE.exists():
        STREAM_FILE.write_text("", encoding="utf-8")

    print(f"[Producer] {len(messages)} messages -> {STREAM_FILE} (interval={interval}s)")
    for index, message in enumerate(messages, start=1):
        message["ingested_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with STREAM_FILE.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(message, ensure_ascii=False) + "\n")
        print(f"[{index:02d}/{len(messages)}] {message['msg_id']} {message['text'][:80]}")
        if interval > 0 and index != len(messages):
            time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay mock chat messages")
    parser.add_argument("--interval", type=float, default=5.0, help="Seconds between messages; use 0 for fast replay")
    parser.add_argument("--reset", action="store_true", help="Clear the stream before replay")
    args = parser.parse_args()
    run(args.interval, args.reset)
