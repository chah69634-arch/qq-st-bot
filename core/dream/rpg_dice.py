"""Bounded deterministic dice for the RPG Dream kernel."""

from __future__ import annotations

import hashlib
import random
import secrets
from dataclasses import asdict, dataclass

from core.dream.rpg_models import RollSpec


@dataclass(frozen=True)
class DiceResolution:
    seed: str
    nonce: str
    faces: tuple[int, ...]
    total: int
    outcome: str

    def audit_dict(self) -> dict:
        return asdict(self)


def generate_seed() -> tuple[str, str]:
    return secrets.token_hex(32), secrets.token_hex(16)


def resolve_roll(spec: RollSpec, *, seed: str, nonce: str) -> DiceResolution:
    """Replayable NdM+modifier vs DC. No expression parsing or code evaluation."""
    material = f"{seed}:{nonce}:{spec.dice_count}:{spec.dice_sides}:{spec.modifier}:{spec.dc}".encode()
    rng = random.Random(int.from_bytes(hashlib.sha256(material).digest(), "big"))
    faces = tuple(rng.randint(1, spec.dice_sides) for _ in range(spec.dice_count))
    total = sum(faces) + spec.modifier
    if all(face == 1 for face in faces):
        outcome = "critical_failure"
    elif all(face == spec.dice_sides for face in faces) and total >= spec.dc:
        outcome = "critical_success"
    elif total >= spec.dc:
        outcome = "success"
    elif total == spec.dc - 1:
        outcome = "success_with_cost"
    else:
        outcome = "failure"
    return DiceResolution(seed=seed, nonce=nonce, faces=faces, total=total, outcome=outcome)
