import pytest

from core.dream.rpg_dice import resolve_roll
from core.dream.rpg_models import RollSpec


def test_same_seed_replays_exactly():
    spec = RollSpec(dice_count=2, dice_sides=6, modifier=1, dc=8)
    assert resolve_roll(spec, seed="a" * 64, nonce="b" * 32) == resolve_roll(spec, seed="a" * 64, nonce="b" * 32)


@pytest.mark.parametrize("field,value", [("dice_count", 0), ("dice_sides", 101), ("modifier", 51), ("dc", 201)])
def test_roll_spec_is_strictly_bounded(field, value):
    raw = {"dice_count": 1, "dice_sides": 6, "modifier": 0, "dc": 5, field: value}
    with pytest.raises(Exception):
        RollSpec.model_validate(raw)
