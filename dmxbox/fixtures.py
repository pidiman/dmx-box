"""Svetlá: knižnica modelov (profiles/*.yaml) + môj zoznam svetiel (rig.yaml) a zápis do DMX rámca.

- Model (profil) opisuje kanály svetla podľa manuálu: logické meno + funkcia (fn) pre engine.
- Zoznam svetiel (rig.yaml) sú konkrétne kusy: značka (label, napr. SVETLO1), model, mód, adresa.
- Každé uloženie zoznamu prejde kontrolou: adresy 1–512, žiadne prekrývanie kanálov
  (okrem zámerného zrkadlenia rovnakého modelu na rovnakej adrese), jedinečné značky.
- Pri prvom spustení sa rig.yaml vytvorí z rig.default.yaml; pred každým uložením sa zálohuje.
"""

from __future__ import annotations

import copy
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import ROOT, resolve

FUNCTIONS = {
    "dimmer": "Jas (dimmer)", "red": "Červená", "green": "Zelená", "blue": "Modrá", "white": "Biela",
    "amber": "Jantárová", "uv": "UV", "strobe": "Strobo", "pan": "Pan", "pan_fine": "Pan jemne",
    "tilt": "Tilt", "tilt_fine": "Tilt jemne", "pt_speed": "Rýchlosť pohybu", "color_wheel": "Farebné koliesko",
    "gobo": "Gobo", "prism": "Hranol", "focus": "Zaostrenie", "macro": "Makro / mód", "speed": "Rýchlosť makra",
    "motor": "Motor (derby)", "laser": "Laser", "fog": "Dym", "program": "Program / auto (0 = DMX)",
    "reset": "Reset", "effect": "Efekt", "other": "Iné (drží hodnotu)",
}
TYPES = {"par": "PAR / reflektor", "bar": "LED lišta", "moving_head": "Moving head", "effect": "Efekt (derby, laser…)",
         "fog": "Dymostroj", "other": "Iné"}
POSITIONS = {"left": "vľavo", "center": "stred", "right": "vpravo"}
MOUNTS = {"ceiling": "Strop / truss (zavesená)", "floor": "Zem / stôl (stojí)"}
LABEL_RE = re.compile(r"^[A-Z0-9_-]{1,12}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
MAX_BACKUPS = 10


def clamp8(v: float) -> int:
    return 0 if v <= 0 else 255 if v >= 255 else int(round(v))


class RigError(ValueError):
    """Chyba zoznamu svetiel so správou pre používateľa."""


# --- modely -----------------------------------------------------------------------

def user_dir() -> Path:
    """Vlastné modely z appky (DMXBOX_USER_PROFILES ich presmeruje, napr. v testoch)."""
    return Path(os.environ.get("DMXBOX_USER_PROFILES") or ROOT / "profiles" / "user")


def profile_dirs() -> list[Path]:
    return [ROOT / "profiles", user_dir()]


def load_profiles() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for d in profile_dirs():
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.yaml")):
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            pid = data.get("id") or p.stem
            data["id"] = pid
            data["user"] = d == user_dir()
            out[pid] = data
    return out


def mode_channels(profile: dict, mode: str) -> list[dict]:
    m = (profile.get("modes") or {}).get(mode)
    if not m:
        raise RigError(f"model {profile.get('name')} nemá mód {mode}")
    return m.get("channels") or []


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower().translate(str.maketrans(
        "áäčďéěíĺľňóôŕřšťúůýž", "aacdeeillnoorrstuuyz"))).strip("-")
    return s[:40] or "model"


def save_user_profile(data: dict) -> dict:
    """Nový model z appky (editor kanálov) → profiles/user/<id>.yaml."""
    name = str(data.get("name", "")).strip()
    if not name:
        raise RigError("zadaj meno modelu")
    typ = data.get("type", "other")
    if typ not in TYPES:
        raise RigError("neznámy typ svetla")
    mode = str(data.get("mode") or "").strip() or f"{len(data.get('channels') or [])}ch"
    chans = []
    seen = set()
    for i, ch in enumerate(data.get("channels") or [], 1):
        fn = ch.get("fn", "other")
        if fn not in FUNCTIONS:
            raise RigError(f"kanál {i}: neznáma funkcia")
        nm = re.sub(r"[^a-z0-9_]", "_", str(ch.get("name") or fn).lower())[:24] or fn
        base, k = nm, 2
        while nm in seen:                    # mená kanálov v móde musia byť jedinečné
            nm, k = f"{base}_{k}", k + 1
        seen.add(nm)
        c = {"name": nm, "fn": fn}
        v = ch.get("value")
        if v not in (None, ""):
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise RigError(f"kanál {i}: hodnota musí byť číslo 0–255") from None
            if not 0 <= v <= 255:
                raise RigError(f"kanál {i}: hodnota musí byť 0–255")
            c["value"] = v
        chans.append(c)
    if not 1 <= len(chans) <= 64:
        raise RigError("model musí mať 1–64 kanálov")
    profiles = load_profiles()
    pid = data.get("id") or slug(name)
    if pid in profiles and not profiles[pid].get("user"):
        pid = f"{pid}-vlastny"
    prof = {"id": pid, "name": name, "manufacturer": data.get("manufacturer", ""), "type": typ,
            "notes": data.get("notes", "Vytvorené v appke."), "modes": {mode: {"channels": chans}}}
    d = user_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{pid}.yaml").write_text(yaml.safe_dump(prof, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return prof


# --- svetlo v rámci zoznamu --------------------------------------------------------

@dataclass
class Fixture:
    key: str
    name: str
    start: int
    channels: dict[str, int]
    ranges: dict = field(default_factory=dict)
    values: dict = field(default_factory=dict)
    limits: dict = field(default_factory=dict)
    label: str = ""
    profile: str = ""
    mode: str = ""
    type: str = "other"
    fns: dict[str, str] = field(default_factory=dict)     # logické meno → funkcia
    position: str = "center"
    defaults: dict[str, int] = field(default_factory=dict)  # pevné hodnoty kanálov z modelu
    mount: str = "ceiling"     # moving head: ceiling = zavesená, floor = stojí na zemi (pan/tilt otočené)

    @property
    def footprint(self) -> int:
        return max(self.channels.values(), default=0)

    def addr(self, ch: str) -> int | None:
        """Absolútna DMX adresa (1–512) logického kanála, alebo None."""
        rel = self.channels.get(ch)
        if rel is None or self.start is None:
            return None
        return self.start + rel - 1

    def set(self, frame: bytearray, ch: str, value: float) -> None:
        a = self.addr(ch)
        if a is not None and 1 <= a <= len(frame):
            frame[a - 1] = clamp8(value)

    def get(self, frame: bytearray, ch: str) -> int:
        a = self.addr(ch)
        return frame[a - 1] if a is not None else 0

    def aim(self, ch: str, value01: float) -> int:
        """Pan/tilt 0–1 z efektu → DMX. Hlava na zemi je hore nohami oproti zavesenej:
        otočí pan aj tilt, aby efekty mierili rovnako (cez parket, nie do očí/stropu)."""
        v = max(0.0, min(1.0, value01))
        if self.mount == "floor" and ch in ("pan", "tilt"):
            v = 1.0 - v
        return self.limit(ch, 255 * v)

    def limit(self, ch: str, value: float) -> int:
        """Premietne 0–255 do povoleného rozsahu kanála (napr. tilt)."""
        lo, hi = self.limits.get(ch, (0, 255))
        return clamp8(lo + (hi - lo) * clamp8(value) / 255)

    def by_fn(self, fn: str) -> list[str]:
        return [n for n, f in self.fns.items() if f == fn]


class Rig:
    """Zapnuté svetlá + spoločný DMX rámec."""

    def __init__(self, fixtures: dict[str, Fixture], universe_channels: int = 32,
                 entries: list[dict] | None = None):
        self.fx = fixtures
        self.universe_channels = universe_channels
        self.entries = entries or []          # celý zoznam vrátane vypnutých (pre appku)

    def __getitem__(self, key: str) -> Fixture:
        return self.fx[key]

    def __contains__(self, key: str) -> bool:
        return key in self.fx

    def new_frame(self) -> bytearray:
        return bytearray(512)


def build_fixture(e: dict, profiles: dict[str, dict]) -> Fixture:
    prof = profiles.get(e["profile"])
    if not prof:
        raise RigError(f"{e.get('label')}: neznámy model {e['profile']}")
    chans = mode_channels(prof, e["mode"])
    m = prof["modes"][e["mode"]]
    limits = {k: tuple(v) for k, v in (m.get("limits") or {}).items()}
    limits.update({k: tuple(v) for k, v in (e.get("limits") or {}).items()})
    return Fixture(
        key=e["id"], name=e.get("name") or prof["name"], start=int(e["address"]),
        channels={c["name"]: i for i, c in enumerate(chans, 1)},
        ranges=m.get("ranges") or {}, values=m.get("values") or {}, limits=limits,
        label=e.get("label", ""), profile=e["profile"], mode=e["mode"], type=prof.get("type", "other"),
        fns={c["name"]: c.get("fn", "other") for c in chans}, position=e.get("position", "center"),
        defaults={c["name"]: int(c["value"]) for c in chans if c.get("value") is not None},
        mount=e.get("mount") if e.get("mount") in MOUNTS else "ceiling")


# --- kontrola zoznamu --------------------------------------------------------------

def footprint_of(e: dict, profiles: dict[str, dict]) -> int:
    prof = profiles.get(e.get("profile", ""))
    if not prof:
        raise RigError(f"neznámy model {e.get('profile')}")
    return len(mode_channels(prof, e.get("mode", "")))


def validate(entries: list[dict], profiles: dict[str, dict]) -> list[str]:
    """Vráti zoznam chýb (prázdny = v poriadku)."""
    errors: list[str] = []
    ids, labels = set(), set()
    spans: list[tuple[int, int, dict]] = []
    for e in entries:
        lab = str(e.get("label", ""))
        who = lab or e.get("id", "?")
        if not ID_RE.match(str(e.get("id", ""))):
            errors.append(f"{who}: neplatné interné id")
        if e.get("id") in ids:
            errors.append(f"{who}: id {e.get('id')} je už použité")
        ids.add(e.get("id"))
        if not LABEL_RE.match(lab):
            errors.append(f"{who}: značka môže mať 1–12 znakov A–Z, 0–9, - a _")
        if lab in labels:
            errors.append(f"značka {lab} je už použitá")
        labels.add(lab)
        try:
            n = footprint_of(e, profiles)
        except RigError as ex:
            errors.append(f"{who}: {ex}")
            continue
        try:
            a = int(e.get("address", 0))
        except (TypeError, ValueError):
            errors.append(f"{who}: adresa musí byť číslo")
            continue
        if a < 1 or a + n - 1 > 512:
            errors.append(f"{who}: adresa {a} + {n} kanálov presahuje rozsah 1–512")
            continue
        spans.append((a, a + n - 1, e))
    for i, (a1, b1, e1) in enumerate(spans):
        for a2, b2, e2 in spans[i + 1:]:
            if a1 <= b2 and a2 <= b1:
                mirror = (a1 == a2 and e1.get("profile") == e2.get("profile") and e1.get("mode") == e2.get("mode")
                          and (e1.get("mirror") or e2.get("mirror")))
                if not mirror:
                    lo, hi = max(a1, a2), min(b1, b2)
                    errors.append(f"{e2.get('label')} ({a2}–{b2}) sa prekrýva so {e1.get('label')} ({a1}–{b1}) "
                                  f"na kanáloch {lo}–{hi}")
    return errors


def free_address(entries: list[dict], profiles: dict[str, dict], footprint: int,
                 exclude: str | None = None) -> int | None:
    """Prvá adresa, kam sa zmestí `footprint` kanálov bez prekrytia."""
    used = []
    for e in entries:
        if e.get("id") == exclude:
            continue
        try:
            a = int(e["address"])
            used.append((a, a + footprint_of(e, profiles) - 1))
        except (RigError, KeyError, ValueError, TypeError):
            continue
    a = 1
    for lo, hi in sorted(used):
        if a + footprint - 1 < lo:
            return a
        a = max(a, hi + 1)
    return a if a + footprint - 1 <= 512 else None


def channel_map(entries: list[dict], profiles: dict[str, dict]) -> list[dict]:
    """Obsadené rozsahy pre mapu kanálov v appke."""
    out = []
    for e in entries:
        try:
            n = footprint_of(e, profiles)
        except RigError:
            continue
        a = int(e.get("address", 0))
        out.append({"id": e.get("id"), "label": e.get("label"), "from": a, "to": a + n - 1,
                    "enabled": e.get("enabled", True)})
    return out


# --- súbory ---------------------------------------------------------------------------

class RigStore:
    """Načítanie a bezpečné ukladanie rig.yaml (validácia + záloha)."""

    def __init__(self, path: str | Path = "rig.yaml", default: str | Path = "rig.default.yaml"):
        self.path = resolve(path)
        self.default = resolve(default)
        self.universe_channels = 40

    def load_entries(self) -> list[dict]:
        src = self.path if self.path.exists() else self.default
        data = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
        self.universe_channels = int(data.get("universe_channels", self.universe_channels))
        return [dict(e) for e in (data.get("fixtures") or [])]

    def save(self, entries: list[dict]) -> None:
        errors = validate(entries, load_profiles())
        if errors:
            raise RigError("; ".join(errors))
        if self.path.exists():
            bdir = self.path.parent / "rig.backup"
            bdir.mkdir(exist_ok=True)
            shutil.copy2(self.path, bdir / time.strftime("rig-%Y%m%d-%H%M%S.yaml"))
            for old in sorted(bdir.glob("rig-*.yaml"))[:-MAX_BACKUPS]:
                old.unlink()
        body = yaml.safe_dump({"fixtures": entries, "universe_channels": self.universe_channels},
                              allow_unicode=True, sort_keys=False)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("# DMX-BOX – môj zoznam svetiel (upravuje appka: Nastavenia boxu → Svetlá)\n" + body,
                       encoding="utf-8")
        tmp.replace(self.path)

    def build(self, entries: list[dict] | None = None) -> Rig:
        entries = copy.deepcopy(entries if entries is not None else self.load_entries())
        profiles = load_profiles()
        fixtures = {}
        for e in entries:
            e.setdefault("enabled", True)
            if e["enabled"]:
                fixtures[e["id"]] = build_fixture(e, profiles)
        end = max((f.start + f.footprint - 1 for f in fixtures.values()), default=0)
        return Rig(fixtures, max(self.universe_channels, -(-end // 8) * 8), entries)


def load_rig(path: str | Path = "rig.yaml") -> Rig:
    return RigStore(path).build()
