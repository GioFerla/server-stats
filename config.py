"""Validated installation settings. Only public presentation values reach HTML/CSS."""
from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo


def text(env, name, default):
    value = env.get(name, default).strip()
    if not value or len(value) > 200 or any(ord(c) < 32 for c in value):
        raise ValueError(f'{name}: use 1–200 characters without control characters')
    return value


def number(env, name, default, minimum, maximum, kind=float):
    value = kind(env.get(name, str(default)))
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f'{name}: expected {minimum}–{maximum}')
    return value


@dataclass(frozen=True)
class Settings:
    name: str
    label: str
    heading: str
    accent: str
    secondary: str
    sample_seconds: float
    history_seconds: int
    timezone: ZoneInfo
    initial_price: float
    proc: Path
    sys: Path
    root: Path
    energy_db: Path

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        colors = [env.get(key, default) for key, default in
                  [('STATS_ACCENT', '#63e6b4'), ('STATS_SECONDARY', '#729dff')]]
        for color in colors:
            if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
                raise ValueError('STATS_ACCENT and STATS_SECONDARY must be #RRGGBB colors')
        sample = number(env, 'STATS_SAMPLE_SECONDS', 1, 0.25, 10)
        history = number(env, 'STATS_HISTORY_SECONDS', 600, 60, 3600, int)
        return cls(
            text(env, 'STATS_NAME', 'Server'), text(env, 'STATS_LABEL', 'Stats'),
            text(env, 'STATS_HEADING', 'Il server, a colpo d’occhio.'), *colors,
            sample, history, ZoneInfo(env.get('STATS_TIMEZONE', 'Europe/Rome')),
            number(env, 'STATS_INITIAL_PRICE', 0.30, 0, 100),
            Path(env.get('HOST_PROC', '/host/proc')), Path(env.get('HOST_SYS', '/host/sys')),
            Path(env.get('HOST_ROOT', '/host/root')), Path(env.get('ENERGY_DB', '/data/energy.sqlite3')))

    @property
    def history_samples(self):
        return math.ceil(self.history_seconds / self.sample_seconds)
