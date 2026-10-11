"""Bounded hash-chain research staging. This is NOT the trading truth database."""

import argparse
import json
import os
from pathlib import Path
from typing import Any

from app.bars import payload_hash
from app.realtime_engine import RealtimeEngine
from app.realtime_models import RealtimeEvent


class ReplayJournal:
    def __init__(self, path: Path, max_bytes: int = 128 * 1024 * 1024) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Every session gets a new UUID; never append to an unverified old chain.
        self.file = path.open("x", encoding="utf-8")
        self.sequence, self.previous = 0, "0" * 64
        self.size, self.max_bytes = 0, max_bytes

    def append(self, event: RealtimeEvent | None, checkpoint: str | None = None) -> None:
        record = dict(
            sequence=self.sequence,
            previous=self.previous,
            event=event.model_dump(mode="json") if event else None,
            checkpoint=checkpoint,
        )
        digest = payload_hash(record)
        line = json.dumps({**record, "hash": digest}, ensure_ascii=False) + "\n"
        size = len(line.encode())
        if self.size + size > self.max_bytes:
            raise OSError("replay journal budget exhausted; research stopped")
        self.file.write(line)
        self.file.flush()
        os.fsync(self.file.fileno())
        self.size += size
        self.sequence += 1
        self.previous = digest

    def close(self) -> None:
        self.file.close()


def replay(path: Path) -> dict[str, Any]:
    engine, previous, checkpoints, events = RealtimeEngine(), "0" * 64, 0, 0
    with path.open(encoding="utf-8") as stream:
        for sequence, line in enumerate(stream):
            record = json.loads(line)
            digest = record.pop("hash")
            if (
                record["sequence"] != sequence
                or record["previous"] != previous
                or payload_hash(record) != digest
            ):
                raise ValueError("replay chain corrupted")
            previous = digest
            if record["event"] is not None:
                engine.apply(RealtimeEvent.model_validate(record["event"]))
                events += 1
            if record["checkpoint"] is not None:
                if payload_hash(engine.snapshot()) != record["checkpoint"]:
                    raise ValueError("replay decision checkpoint mismatch")
                checkpoints += 1
    if events == 0 or checkpoints == 0:
        raise ValueError("replay requires events and a verified checkpoint")
    return dict(
        events=events, checkpoints=checkpoints, final_hash=previous, snapshot=engine.snapshot()
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify and replay a P2 research session")
    parser.add_argument("journal", type=Path)
    result = replay(parser.parse_args().journal)
    print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
