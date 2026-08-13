"""The stress scenario library, loaded from cited index levels.

Scenarios are stored in ``data/scenarios/scenarios.json`` as the two index
closing levels the magnitude is derived from, never as a percentage. The
percentage is recomputed here at load time.

That is a deliberate design choice and it is the thing to say if asked where the
numbers came from. A scenario asserted as ``-38%`` cannot be checked by anyone,
including its author six months later. A scenario stored as "S&P 500 closed at
1468.36 on 2007-12-31 and 903.25 on 2008-12-31" can be checked in thirty seconds
against any data provider, and if a level is wrong, fixing that one number fixes
every figure downstream of it.

It also forces a distinction that gets blurred constantly: the S&P 500's 2008
**calendar-year** price return was about -38%, while its **peak-to-trough**
drawdown from October 2007 to March 2009 was about -57%. Both are real, they
describe different things, and quoting one while describing the other is the most
common piece of sloppiness in this whole area. Both ship here, labelled by
``basis``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

_DEFAULT_PATH = get_settings().data_path / "scenarios" / "scenarios.json"


@dataclass(frozen=True)
class Scenario:
    name: str
    universe: str
    label: str
    index: str
    peak_date: str
    peak_level: float
    trough_date: str
    trough_level: float
    basis: str
    source: str
    verification_status: str
    note: str

    @property
    def shock_pct(self) -> float:
        """Negative decimal fraction, recomputed from the levels every time."""
        return self.trough_level / self.peak_level - 1.0

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "universe": self.universe,
            "label": self.label,
            "index": self.index,
            "peak_date": self.peak_date,
            "peak_level": self.peak_level,
            "trough_date": self.trough_date,
            "trough_level": self.trough_level,
            "shock_pct": self.shock_pct,
            "basis": self.basis,
            "source": self.source,
            "verification_status": self.verification_status,
            "note": self.note,
            "derivation": (
                f"{self.trough_level} / {self.peak_level} - 1 = "
                f"{self.shock_pct:.4f} ({self.shock_pct:.2%})"
            ),
        }


@lru_cache
def load_scenarios(path: str | None = None) -> dict[str, Scenario]:
    source = Path(path) if path else _DEFAULT_PATH
    if not source.is_file():
        raise FileNotFoundError(
            f"Scenario library not found at {source}. It ships with the repository at "
            "data/scenarios/scenarios.json; if you are running the backend outside the "
            "repo, set SCENARIOS_PATH."
        )
    payload = json.loads(source.read_text())
    out: dict[str, Scenario] = {}
    for entry in payload["scenarios"]:
        scenario = Scenario(
            name=entry["name"],
            universe=entry["universe"],
            label=entry["label"],
            index=entry["index"],
            peak_date=entry["peak_date"],
            peak_level=float(entry["peak_level"]),
            trough_date=entry["trough_date"],
            trough_level=float(entry["trough_level"]),
            basis=entry["basis"],
            source=entry["source"],
            verification_status=entry["verification_status"],
            note=entry["note"],
        )
        if not 0 < scenario.trough_level < scenario.peak_level:
            raise ValueError(
                f"Scenario {scenario.name}: trough level must be positive and below the "
                "peak level. A 'stress' scenario in which the index rises is a sign "
                "the two levels were entered the wrong way round."
            )
        out[scenario.name] = scenario
    return out


def for_universe(universe: str, path: str | None = None) -> list[Scenario]:
    return [s for s in load_scenarios(path).values() if s.universe == universe]
