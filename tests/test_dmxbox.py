"""Testy bez hardvéru: audio analýza, engine, API."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dmxbox.audio import Analyzer  # noqa: E402
from dmxbox.dmx_out import DMXOut  # noqa: E402
from dmxbox.effects.color import COLOR_FX  # noqa: E402
from dmxbox.effects.movement import MOVE_FX  # noqa: E402
from dmxbox.engine import Engine  # noqa: E402
from dmxbox.fixtures import load_rig  # noqa: E402
from dmxbox.sim import synth_source  # noqa: E402
from dmxbox.fog import FogController  # noqa: E402
from dmxbox.state import Store  # noqa: E402
from dmxbox.styles import LOOKS  # noqa: E402


def run_analyzer(bpm: float, seconds: float = 14, **kw) -> Analyzer:
    an = Analyzer(synth_source(bpm=bpm, seconds=seconds, **kw), silence_seconds=2)
    for blk in synth_source(bpm=bpm, seconds=seconds, **kw):
        an.process(blk)
    return an


@pytest.mark.parametrize("bpm", [90, 124, 140, 174])
def test_bpm_detection(bpm):
    s = run_analyzer(bpm).snapshot()
    assert abs(s.bpm - bpm) < 2.5, s.bpm
    assert s.bpm_confident


def test_beat_phase_locks_to_kick():
    """Po ustálení má byť kick blízko fázy 0 beatu."""
    bpm, rate, hop = 124, 44100, 512
    an = Analyzer(iter(()), silence_seconds=2)
    errs, last = [], 0
    for i, blk in enumerate(synth_source(bpm=bpm, seconds=20)):
        an.process(blk)
        s = an.snapshot()
        t = (i + 1) * hop / rate
        if t > 10 and s.onset_count != last:
            # kick v syntéze padá na celé násobky beatu
            beat_pos = (t / (60 / bpm)) % 1
            if beat_pos < 0.25 or beat_pos > 0.75:
                errs.append(min(s.beat_phase, 1 - s.beat_phase))
        last = s.onset_count
    assert errs and float(np.median(errs)) < 0.2


def test_silence_detected():
    an = Analyzer(iter(()), silence_seconds=1)
    for blk in synth_source(bpm=120, seconds=4):
        an.process(blk * 0.0)
    assert an.snapshot().silent


@pytest.fixture
def engine(tmp_path):
    rig = load_rig()
    an = run_analyzer(128, seconds=8)
    store = Store(tmp_path / "presets.json")
    return Engine(rig, an, store, DMXOut(driver="dry")), an, store


def test_all_fx_produce_valid_frames(engine):
    eng, an, store = engine
    a = an.snapshot()
    for cf in COLOR_FX:
        for mf in MOVE_FX:
            store.update(auto=False, color_fx=cf, move_fx=mf)
            f = eng.compute(a, 1.0)
            assert len(f) == 512 and max(f) <= 255
            assert f[0] == 0, "parbar macro musí byť 0 (priame RGBW)"
            assert f[17] == 0, "spot program musí byť 0 (DMX režim)"


def test_strobe_and_blackout(engine):
    eng, an, store = engine
    a = an.snapshot()
    store.update(strobe=True)
    f = eng.compute(a, 1.0)
    assert 201 <= f[0] <= 255           # parbar strobe makro
    assert f[30] == 255 and f[31] > 0   # Belka strobo/UV jas + rýchlosť
    store.update(strobe=False, blackout=True)
    f = eng.compute(a, 1.0)
    dimmers = [f[3], f[15]] + list(f[20:24]) + list(f[25:32])
    assert not any(dimmers)


def test_tilt_limits(engine):
    eng, an, store = engine
    a = an.snapshot()
    store.update(auto=False, move_fx="tilt_bounce", size=1.0)
    vals = set()
    for k in range(16):
        a.beat_count = k
        vals.add(eng.compute(a, 1.0)[10])  # DMX 11 = tilt
    assert min(vals) >= 40 and max(vals) <= 200


def test_presets_roundtrip(tmp_path):
    st = Store(tmp_path / "p.json")
    st.update(color_fx="rainbow", palette="ice", master=0.5)
    st.save_preset(7)
    st.update(color_fx="split", palette="fire", master=1.0)
    st2 = Store(tmp_path / "p.json")
    s = st2.load_preset(7)
    assert (s.color_fx, s.palette, s.master) == ("rainbow", "ice", 0.5)


def test_dmx_out_delay():
    out = DMXOut(driver="dry", channels=4, delay_ms=100)
    out.submit(bytes([1, 2, 3, 4]))
    assert out._pick() == bytes(4)     # ešte nie je čas
    import time
    time.sleep(0.12)
    assert out._pick() == bytes([1, 2, 3, 4])


def test_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from dmxbox.api import create_app
    from dmxbox.audio_ctl import LineIn
    from dmxbox.main import Box

    rig = load_rig()
    an = run_analyzer(120, seconds=6)
    store = Store(tmp_path / "p.json")
    out = DMXOut(driver="dry")
    box = Box(store, an, Engine(rig, an, store, out), out, LineIn())
    c = TestClient(create_app(box))

    d = c.get("/api/state").json()
    assert set(d["catalog"]["color_fx"]) == set(COLOR_FX)
    assert c.post("/api/fx", json={"wheel": 2, "fx": "snap"}).json()["move_fx"] == "snap"
    assert c.post("/api/settings", json={"color_fx": "nope"}).status_code == 400
    assert c.post("/api/master", json={"value": 2}).json()["master"] == 1.0
    assert c.post("/api/preset/9").status_code == 404
    assert c.put("/api/preset/9").status_code == 200
    assert c.post("/api/preset/9").status_code == 200
    assert c.post("/api/bpm", json={"factor": 2}).status_code == 200
    with c.websocket_connect("/ws") as ws:
        assert "audio" in ws.receive_json()
    assert c.get("/").status_code == 200


def test_fog_hold_limit_and_cooldown():
    from dmxbox.audio import AudioState
    from dmxbox.fog import FogController
    fc = FogController(max_burst_s=10, cooldown_s=30)
    a = AudioState(silent=False)
    on = lambda t, hold, auto=False: fc.update(t, a, hold, auto, 3.0, False)  # noqa: E731
    assert on(0, True)                 # stlačené → dym
    assert on(9.9, True)
    assert not on(10.1, True)          # max 10 s aj pri držaní
    assert not on(20, False)
    assert not on(25, True)            # pauza 30 s, nové stlačenie nič
    assert not on(41, True)            # stále držané od 25 s → treba pustiť
    assert not on(41.5, False)
    assert on(42, True)                # po pauze nový výstrek
    assert not on(43, False)           # pustenie ukončí výstrek


def test_fog_auto_on_drop_and_blackout():
    from dmxbox.audio import AudioState
    from dmxbox.fog import FogController
    fc = FogController(cooldown_s=30)
    quiet = AudioState(silent=False, level=0.2, bass=0.2)
    loud = AudioState(silent=False, level=1.0, bass=1.0)
    t = 0.0
    for _ in range(400):               # 10 s tichšej časti
        assert not fc.update(t, quiet, False, True, 3.0, False)
        t += 0.025
    assert fc.update(t, loud, False, True, 3.0, False)      # drop → auto výstrek
    assert fc.update(t + 2.9, loud, False, True, 3.0, False)
    assert not fc.update(t + 3.1, loud, False, True, 3.0, False)
    fc2 = FogController()
    assert not fc2.update(0, loud, True, False, 3.0, True)   # blackout = nikdy dym


def test_fog_dmx(engine):
    eng, an, store = engine
    a = an.snapshot()
    store.update(fog=True)
    assert eng.compute(a, 100.0)[32] == 255     # DMX 33 = dym
    store.update(fog=False)
    assert eng.compute(a, 100.1)[32] == 0


# --- štýl hudby a fázy skladby ------------------------------------------------

@pytest.mark.parametrize("genre", ["house", "techno", "dnb", "hiphop", "chill", "party"])
def test_genre_classification(genre):
    """Syntetické vzory žánrov (sim.PATTERNS) sa rozpoznajú správne."""
    an = Analyzer(iter(()), silence_seconds=2)
    for blk in synth_source(bpm=None, genre=genre, seconds=40):
        an.process(blk)
    s = an.snapshot()
    assert s.style == genre, (s.style, s.style_scores, s.features)


def test_sections_breakdown_build_drop():
    an = Analyzer(iter(()), silence_seconds=2)
    seen = []
    for blk in synth_source(bpm=None, genre="house", seconds=56, breakdown=(30, 44)):
        an.process(blk)
        s = an.snapshot()
        if not seen or seen[-1][0] != s.section:
            seen.append((s.section, s.t))
    names = [n for n, _ in seen]
    assert names[:2] == ["main", "breakdown"]
    assert "build" in names
    drop_t = dict((n, t) for n, t in seen)["drop"]
    assert 43 <= drop_t <= 46.5                 # na prvý kick po breakdowne
    assert an.snapshot().drop_count == 1


def test_style_fixed_and_auto(engine):
    eng, an, store = engine
    a = an.snapshot()
    a.style = "chill"
    store.update(auto=True, style="auto")
    eng.compute(a, 1.0)
    assert eng.status.style == "chill" and eng.status.style_auto
    assert eng.status.color_fx in {c for c, _ in LOOKS["chill"].sets}
    store.update(style="techno")
    eng.compute(a, 1.1)
    assert eng.status.style == "techno" and not eng.status.style_auto


def test_breakdown_calm_and_drop_hit(engine):
    eng, an, store = engine
    a = an.snapshot()
    a.silent = False
    store.update(auto=True, style="dnb", laser=True)
    a.section = "breakdown"
    f = eng.compute(a, 1.0)
    assert (eng.status.color_fx, eng.status.move_fx) == LOOKS["dnb"].calm
    assert f[29] == 0 and f[31] == 0            # bez lasera a bez stroboskopu
    a.section, a.drop_count = "drop", a.drop_count + 1
    f = eng.compute(a, 1.1)
    assert 201 <= f[0] <= 255                   # krátke strobo na prvú dobu dropu
    a.beat_count += 2
    f = eng.compute(a, 1.2)
    assert f[0] == 0                            # po 1 dobe späť na FX


def test_fog_on_drop_event(engine):
    eng, an, store = engine
    a = an.snapshot()
    a.silent = False
    store.update(fog_auto=True, style="techno")
    assert eng.compute(a, 200.0)[32] == 0
    a.drop_count += 1
    assert eng.compute(a, 200.1)[32] == 255
    store.update(style="chill")                 # chill: dym na drop nie
    eng.fog = FogController()
    a.drop_count += 1
    assert eng.compute(a, 300.0)[32] == 0


def test_api_style(tmp_path):
    from fastapi.testclient import TestClient

    from dmxbox.api import create_app
    from dmxbox.audio_ctl import LineIn
    from dmxbox.main import Box

    rig = load_rig()
    an = run_analyzer(120, seconds=6)
    store = Store(tmp_path / "p.json")
    out = DMXOut(driver="dry")
    box = Box(store, an, Engine(rig, an, store, out), out, LineIn())
    c = TestClient(create_app(box))
    d = c.get("/api/state").json()
    assert {s["key"] for s in d["catalog"]["styles"]} == {"party", "dnb", "techno", "house", "hiphop", "chill"}
    assert "music" in d and "section" in d["engine"]
    assert c.post("/api/settings", json={"style": "dnb"}).json()["style"] == "dnb"
    assert c.post("/api/settings", json={"style": "polka"}).status_code == 400
