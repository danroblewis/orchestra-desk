"""The operator's guide (``orchestra_desk/guide.md``) ships in the package, and every TOML example in
it is a configuration the Desk accepts: an example that drifts from the contract fails here."""

import re
import tomllib
from pathlib import Path

import pytest

import orchestra_desk
from orchestra_desk.config import CONDITION_KEYS, DESK_KEYS, RULE_KEYS, problems

GUIDE = Path(orchestra_desk.__file__).parent / "guide.md"


def blocks() -> list[str]:
    return re.findall(r"```toml\n(.*?)```", GUIDE.read_text(encoding="utf-8"), re.DOTALL)


def test_the_guide_is_in_the_package():
    assert GUIDE.is_file()
    assert len(blocks()) >= 5


@pytest.mark.parametrize("i", range(len(blocks())))
def test_each_example_is_accepted(i):
    raw = tomllib.loads(blocks()[i])
    raw.setdefault("desk", {})                 # a fragment of [desk.conditions] or [desk.ledger] alone
    settings, errors = problems(raw)
    assert errors == [], f"example {i + 1} of the guide: {errors}"
    assert settings is not None


def test_every_key_the_desk_reads_is_named():
    text = GUIDE.read_text(encoding="utf-8")
    for key in DESK_KEYS | CONDITION_KEYS | RULE_KEYS | {"defaults", "types"}:
        assert f"`{key}`" in text or f"{key} =" in text or f"[desk.{key}" in text, f"the guide never names {key}"
