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
from dmxbox.sim import synth_source  # noqa: E402
from dmxbox.fog import FogController  # noqa: E402
from dmxbox.state import Store  # noqa: E402
from dmxbox.styles import LOOKS  # noqa: E402


@pytest.fixture(autouse=True)
def _user_profiles(tmp_path, monkeypatch):
    """Vlastné modely z testov nikdy nejdú do skutočného profiles/user."""
    monkeypatch.setenv("DMXBOX_USER_PROFILES", str(tmp_path / "user-profiles"))


def rig_all():
    """Všetky svetlá z predvoleného zoznamu vrátane vypnutého dymostroja (testy dymu)."""
    from dmxbox.fixtures import RigStore
    rs = RigStore(Path("/nonexistent-rig.yaml"))
    entries = rs.load_entries()
    for e in entries:
        e["enabled"] = True
    return rs.build(entries)


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
    rig = rig_all()
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

    rig = rig_all()
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
    assert "Ako dnes" in c.get("/").text          # vstupná obrazovka
    assert "wheel-color" in c.get("/ovladanie").text   # pôvodné ovládanie


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

    rig = rig_all()
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


# --- vstupná obrazovka: scenáre a systém ---------------------------------------

def _box(tmp_path):
    from dmxbox.audio_ctl import LineIn
    from dmxbox.main import Box
    from dmxbox.scenario import ScenarioStore
    from dmxbox.sim import mix_source

    rig = rig_all()
    an = run_analyzer(120, seconds=6)
    store = Store(tmp_path / "p.json")
    out = DMXOut(driver="dry")
    sources = {"live": lambda: synth_source(bpm=124, seconds=5), "demo": lambda: mix_source()}
    return Box(store, an, Engine(rig, an, store, out), out, LineIn(), sources,
               ScenarioStore(tmp_path / "scenario.json"))


def test_scenarios_api(tmp_path):
    from fastapi.testclient import TestClient

    from dmxbox.api import create_app
    from dmxbox.scenario import ScenarioStore

    box = _box(tmp_path)
    c = TestClient(create_app(box))
    d = c.get("/api/scenarios").json()
    assert {s["id"] for s in d["scenarios"]} >= {"bt", "spotify", "linein", "btspeaker", "ambient", "demo"}
    assert d["last"] is None
    r = c.post("/api/scenario", json={"id": "demo", "style": "techno", "laser": False}).json()
    assert r["ok"]
    s = box.store.get()
    assert (s.style, s.laser, s.auto, s.ambient) == ("techno", False, True, False)
    assert box.analyzer._pending_source is not None        # demo → simulácia
    assert ScenarioStore(tmp_path / "scenario.json").last["id"] == "demo"   # zapamätané
    assert c.get("/api/scenarios").json()["last_summary"].startswith("Demo")
    assert c.post("/api/scenario", json={"id": "xyz"}).status_code == 400
    assert c.post("/api/scenario", json={"id": "bt", "style": "polka"}).status_code == 400
    assert c.get("/api/system").status_code == 200
    assert c.post("/api/system/bt/forget", json={"mac": "nope"}).status_code == 400
    assert c.post("/api/system/power", json={"value": "format"}).status_code == 400


def test_ambient_lights_without_music(tmp_path):
    box = _box(tmp_path)
    a = box.analyzer.snapshot()
    a.silent = True
    box.store.update(ambient=True, strobe=False)
    f = box.engine.compute(a, 100.0)
    assert not box.engine.status.idle and box.engine.status.style == "chill"
    assert f[29] == 0                                       # bez lasera
    box.store.update(ambient=False)
    box.engine.compute(a, 100.1)
    assert box.engine.status.idle                           # bez hudby → kľud


def test_system_helpers():
    from dmxbox import system
    from dmxbox.api import Captive

    assert system._split_t(r"Moja\:sieť:72:WPA2") == ["Moja:sieť", "72", "WPA2"]
    assert system._sink_kind("alsa_output.usb-BurrBrown_UCA202-00.analog-stereo") == "usb"
    assert system._sink_kind("alsa_output.platform-3f00b840.mailbox.stereo-fallback") == "jack"
    assert system._sink_kind("bluez_output.AA_BB_CC_DD_EE_FF.1") == "bluetooth"
    cp = Captive()
    assert cp.foreign("captive.apple.com") and cp.foreign("connectivitycheck.gstatic.com:80")
    assert not cp.foreign("10.42.0.1") and not cp.foreign("dmx-box.local:8080") and not cp.foreign("localhost")
    try:
        system.wifi_add("x", "short")
        raise AssertionError
    except system.CmdError:
        pass


def test_pin_protection(tmp_path):
    from fastapi.testclient import TestClient

    from dmxbox.api import create_app
    from dmxbox.auth import Auth

    box = _box(tmp_path)
    box.auth = Auth(tmp_path / "security.json")
    c = TestClient(create_app(box))
    assert c.get("/api/auth").json() == {"required": False, "has_pin": False, "ok": False}
    assert c.get("/api/state").status_code == 200                  # bez PINu otvorené
    assert c.post("/api/auth/required", json={"pin": "1", "on": True}).status_code == 401
    assert c.post("/api/auth/pin", json={"pin": "", "new_pin": "12"}).status_code == 400
    assert c.post("/api/auth/pin", json={"pin": "", "new_pin": "2468"}).status_code == 200
    assert c.post("/api/auth/required", json={"pin": "2468", "on": True}).json()["required"]

    other = TestClient(create_app(box))                           # iný tablet bez cookie
    r = other.get("/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/lock.html")
    assert other.get("/api/state").status_code == 401
    assert other.get("/lock.html").status_code == 200
    assert other.post("/api/auth/pin", json={"pin": "0000", "new_pin": "1111"}).status_code == 401
    assert other.post("/api/auth/login", json={"pin": "9999"}).status_code == 401
    assert other.post("/api/auth/login", json={"pin": "2468"}).status_code == 200
    assert other.get("/api/state").status_code == 200
    with other.websocket_connect("/ws") as ws:
        assert "audio" in ws.receive_json()

    # PIN sa ukladá len ako hash a prežije reštart
    saved = (tmp_path / "security.json").read_text()
    assert "2468" not in saved and Auth(tmp_path / "security.json").required

    # zmena PINu odhlási ostatné zariadenia
    assert c.post("/api/auth/pin", json={"pin": "2468", "new_pin": "13579"}).status_code == 200
    assert other.get("/api/state").status_code == 401
    assert c.get("/api/state").status_code == 200

    # veľa zlých pokusov → pauza
    third = TestClient(create_app(box))
    for _ in range(5):
        third.post("/api/auth/login", json={"pin": "0000"})
    assert third.post("/api/auth/login", json={"pin": "13579"}).status_code == 429
    box.auth._fails.clear()        # testovacie klienty majú rovnakú adresu

    assert c.post("/api/auth/required", json={"pin": "13579", "on": False}).json()["required"] is False
    assert TestClient(create_app(box)).get("/api/state").status_code == 200


def test_stereo_viz_and_nowplaying():
    from dmxbox.nowplaying import parse_objects

    an = Analyzer(iter(()), silence_seconds=2)
    for blk in synth_source(bpm=124, seconds=9):
        an.process(np.stack([blk, blk * 0.2], axis=1))      # stereo: pravý kanál tichší
    s = an.snapshot()
    assert len(s.viz_l) == 24 and len(s.viz_r) == 24
    assert max(s.viz_l) > 0.1 and sum(s.viz_l) > sum(s.viz_r)
    assert s.bpm_confident                                    # analýza ide ďalej z mixu
    sample = {"type": "a{oa{sa{sv}}}", "data": [{
        "/org/bluez/hci0/dev_AA/player0": {"org.bluez.MediaPlayer1": {
            "Status": {"type": "s", "data": "playing"},
            "Track": {"type": "a{sv}", "data": {"Title": {"type": "s", "data": "Chimera"},
                                                "Artist": {"type": "s", "data": "Faders"}}}}},
        "/org/bluez/hci0/dev_AA": {"org.bluez.Device1": {"Alias": {"type": "s", "data": "iPad"}}}}]}
    t = parse_objects(sample)
    assert (t.title, t.artist, t.source, t.status) == ("Chimera", "Faders", "iPad", "playing")
    assert parse_objects({"type": "a{oa{sa{sv}}}", "data": [{}]}).title == ""


def test_airplay_metadata_and_scenario(tmp_path):
    import base64

    from fastapi.testclient import TestClient

    from dmxbox.api import create_app
    from dmxbox.nowplaying import AirPlayMeta, Track, stub

    def item(t, c, d=None):
        x = f"<item><type>{t.encode().hex()}</type><code>{c.encode().hex()}</code><length>{len(d or '')}</length>"
        if d is not None:
            x += f'\n<data encoding="base64">\n{base64.b64encode(d.encode()).decode()}</data>'
        return x + "</item>\n"

    ap = AirPlayMeta()
    text = item("ssnc", "snam", "Jakubov iPhone") + item("ssnc", "pbeg") + item("core", "minm", "Chimera") \
        + item("core", "asar", "Faders")
    rest = ap.feed(text[:70])                 # rúra posiela text po kúskoch
    ap.feed(rest + text[70:])
    np_ = stub()
    np_.airplay = ap
    np_.track = Track(title="BT skladba")
    t = np_.track
    assert (t.title, t.artist, t.source) == ("Chimera", "Faders", "Jakubov iPhone")   # AirPlay má prednosť
    ap.feed(item("ssnc", "pend"))
    assert np_.track.title == "BT skladba"

    box = _box(tmp_path)
    c = TestClient(create_app(box))
    assert "airplay" in {s["id"] for s in c.get("/api/scenarios").json()["scenarios"]}
    assert "airplay" in c.get("/api/system").json()
    r = c.post("/api/scenario", json={"id": "airplay", "style": "auto"}).json()
    assert r["ok"]                           # bez shairport-sync len varovanie, scenár beží


# --- správa svetiel ------------------------------------------------------------------

def test_rig_validation_rules():
    from dmxbox import fixtures as fx

    prof = fx.load_profiles()
    base = [{"id": "a", "label": "SVETLO1", "profile": "max-partybar4", "mode": "8ch", "address": 1},
            {"id": "b", "label": "SVETLO2", "profile": "light4me-belka", "mode": "12ch", "address": 21}]
    assert fx.validate(base, prof) == []
    clash = base + [{"id": "c", "label": "PAR1", "profile": "generic-rgbw-par", "mode": "4ch", "address": 30}]
    err = fx.validate(clash, prof)
    assert err and "30–32" in err[0] and "SVETLO2" in err[0]           # presne ktoré kanály
    assert fx.validate(base + [{"id": "c", "label": "svetlo1", "profile": "generic-rgb-par",
                                "mode": "3ch", "address": 100}], prof)  # značka bez ohľadu na… (malé písmená neplatné)
    assert fx.validate(base + [{"id": "c", "label": "SVETLO1", "profile": "generic-rgb-par",
                                "mode": "3ch", "address": 100}], prof)  # duplicitná značka
    assert fx.validate(base + [{"id": "c", "label": "X", "profile": "generic-rgb-par",
                                "mode": "3ch", "address": 511}], prof)  # mimo 512
    mirror = base + [{"id": "c", "label": "BELKA2", "profile": "light4me-belka", "mode": "12ch",
                      "address": 21, "mirror": True}]
    assert fx.validate(mirror, prof) == []                              # zámerné zrkadlenie
    assert fx.free_address(base, prof, 4) == 9                          # medzera 9–20
    assert fx.free_address(base, prof, 16) == 33


def test_rig_api_add_edit_delete_identify(tmp_path):
    from fastapi.testclient import TestClient

    from dmxbox.api import create_app
    from dmxbox.fixtures import ROOT, RigStore

    box = _box(tmp_path)
    box.rig_store = RigStore(tmp_path / "rig.yaml", ROOT / "rig.default.yaml")
    c = TestClient(create_app(box))
    d = c.get("/api/rig").json()
    assert [f["label"] for f in d["fixtures"]] == ["SVETLO1", "SVETLO2", "SVETLO3", "DYM1"]
    assert d["errors"] == [] and any(p["id"] == "generic-rgbw-par" for p in d["profiles"])

    chk = c.post("/api/rig/check", json={"label": "PAR1", "profile": "generic-rgbw-par", "mode": "8ch",
                                         "address": 25}).json()
    assert chk["errors"] and chk["free"] == 37 and chk["footprint"] == 8
    bad = c.post("/api/rig/fixture", json={"label": "PAR1", "profile": "generic-rgbw-par", "mode": "8ch",
                                           "address": 25})
    assert bad.status_code == 400 and "prekrýva" in bad.json()["detail"]
    ok = c.post("/api/rig/fixture", json={"label": "par1", "name": "PAR vľavo", "profile": "generic-rgbw-par",
                                          "mode": "8ch", "address": 37, "position": "left"})
    assert ok.status_code == 200
    new = next(f for f in ok.json()["fixtures"] if f["label"] == "PAR1")   # značka veľkými
    assert new["id"] == "fx1" and new["end"] == 44
    assert "fx1" in box.engine.rig                                         # engine hneď vidí nové svetlo

    # nové svetlo dostáva farby a jas podľa funkcií kanálov
    a = box.analyzer.snapshot()
    a.silent = False
    box.store.update(auto=False, color_fx="color_step", move_fx="hold", master=1.0)
    f = box.engine.compute(a, 1.0)
    assert f[36] > 0 and any(f[37:41])                                     # dimmer 37, RGBW 38–41

    assert c.put("/api/rig/fixture/fx1", json={"address": 1}).status_code == 400   # kolízia s lištou
    assert c.put("/api/rig/fixture/belka", json={"label": "BELKA", "enabled": False}).status_code == 200
    assert "belka" not in box.engine.rig
    assert (tmp_path / "rig.backup").exists()                              # záloha pred zmenou

    assert c.post("/api/rig/identify/fx1").status_code == 200
    import time as _t
    f = box.engine.compute(a, _t.monotonic())
    assert not any(f[:8]) and not any(f[11:36])                            # svieti len PAR1 (hlava len stojí)

    assert c.post("/api/rig/test/fx1", json={"red": 255, "nonsense": 9}).status_code == 200
    f = box.engine.compute(a, _t.monotonic())
    assert f[37] == 255 and sum(f[36:44]) == 255 and not any(f[:8])
    c.post("/api/rig/test-stop")

    prof = c.post("/api/rig/profile", json={"name": "Môj laser", "type": "effect",
                                            "channels": [{"fn": "laser"}, {"fn": "speed"}]}).json()
    assert prof["created"] == "moj-laser"
    exp = c.get("/api/rig/export").json()
    assert "moj-laser" in exp["profiles"]
    assert c.delete("/api/rig/fixture/fx1").status_code == 200
    assert "fx1" not in box.engine.rig
    assert c.post("/api/rig/import", json=exp).status_code == 200          # obnova zo zálohy


def test_generic_laser_follows_laser_switch_and_holds_values(tmp_path):
    from fastapi.testclient import TestClient
    from dmxbox.api import create_app
    from dmxbox.fixtures import ROOT, RigStore
    import time as _t
    box = _box(tmp_path)
    box.rig_store = RigStore(tmp_path / "rig.yaml", ROOT / "rig.default.yaml")
    c = TestClient(create_app(box))
    chans = [{"fn": "laser", "name": "rezim"}, {"fn": "effect", "name": "vzor"}, {"fn": "effect", "name": "rotacia"},
             {"fn": "other"}, {"fn": "other"}, {"fn": "other", "name": "pozicia_x", "value": 64},
             {"fn": "other", "name": "pozicia_y", "value": "64"}, {"fn": "effect"}, {"fn": "other"}, {"fn": "other"}]
    pid = c.post("/api/rig/profile", json={"name": "Laser geo", "type": "effect", "mode": "10ch",
                                           "channels": chans}).json()["created"]
    assert c.post("/api/rig/profile", json={"name": "Zly", "channels": [{"fn": "other", "value": 300}]}).status_code == 400
    r = c.post("/api/rig/fixture", json={"label": "LASER1", "profile": pid, "mode": "10ch", "address": 37})
    assert r.status_code == 200, r.text
    a = box.analyzer.snapshot()
    box.store.update(laser=True, auto=False)
    f = box.engine.compute(a, _t.monotonic())
    assert f[36] == 224 and f[41] == 64 and f[42] == 64 and f[37] == 0       # zvukový mód, stred polohy
    box.store.update(laser=False)
    f = box.engine.compute(a, _t.monotonic())
    assert f[36] == 0 and f[41] == 64                                         # vypnutý, poloha drží
    # úprava modelu: vlastná hodnota zapnutia (auto mód 160)
    chans[0]["value"] = 160
    assert c.post("/api/rig/profile", json={"id": pid, "name": "Laser geo", "type": "effect", "mode": "10ch",
                                            "channels": chans}).status_code == 200
    box.store.update(laser=True)
    f = box.engine.compute(a, _t.monotonic())
    assert f[36] == 160
    # úprava, po ktorej by sa svetlá prekrývali, sa odmietne a model ostane
    assert c.post("/api/rig/fixture", json={"label": "PAR9", "profile": "generic-rgb-par", "mode": "3ch",
                                            "address": 47}).status_code == 200
    bad = c.post("/api/rig/profile", json={"id": pid, "name": "Laser geo", "type": "effect", "mode": "10ch",
                                           "channels": chans + [{"fn": "other"}]})
    assert bad.status_code == 400 and "prekrývali" in bad.text
    prof = next(p for p in c.get("/api/rig").json()["profiles"] if p["id"] == pid)
    assert len(prof["modes"]["10ch"]) == 10


def test_airplay_title_after_missed_start():
    """Box reštartovaný počas hrania: pbeg neprišiel, názov skladby sa aj tak zobrazí."""
    import base64
    from dmxbox.nowplaying import NowPlaying
    np_ = NowPlaying(); np_.available = False
    def item(t, c, d=None):
        x = f"<item><type>{t.encode().hex()}</type><code>{c.encode().hex()}</code><length>{len(d or '')}</length>"
        if d is not None:
            x += f"\n<data encoding=\"base64\">\n{base64.b64encode(d.encode()).decode()}</data>"
        return x + "</item>\n"
    np_.airplay.feed(item("core", "minm", "Strobe") + item("core", "asar", "deadmau5"))
    assert np_.track.title == "Strobe" and np_.track.status == "playing"


def test_sys_stats(tmp_path):
    from dmxbox.system import SysStats
    (tmp_path / "stat").write_text("cpu  100 0 100 800 0 0 0 0 0 0\n")
    (tmp_path / "meminfo").write_text("MemTotal: 1000 kB\nMemFree: 100 kB\nMemAvailable: 250 kB\n")
    (tmp_path / "temp").write_text("52437\n")
    s = SysStats(ttl=0, proc=tmp_path, thermal=tmp_path / "temp", disk=str(tmp_path))
    v = s.get()
    assert v["ram"] == 75 and v["temp"] == 52.4 and 0 <= v["sd"] <= 100
    (tmp_path / "stat").write_text("cpu  150 0 150 900 0 0 0 0 0 0\n")        # +100 práca, +100 idle
    assert s.get()["cpu"] == 50
    missing = SysStats(ttl=0, proc=tmp_path / "nie", thermal=tmp_path / "nie", disk="/nie/je")
    assert missing.get() is None


class _FakeBT:
    """Simulovaný bluetoothctl/pactl pre SpeakerWatch."""
    from dmxbox.system import CmdError

    def __init__(self):
        self.connected = {"AA:BB:CC:DD:EE:FF": "JBL Charge 3"}
        self.sink = "bluez_output.AA_BB_CC_DD_EE_FF.1"
        self.calls = []
        self.fail = False

    def has(self, _):
        return True

    def _bt_devices(self, kind):
        return list(self.connected.items())

    def _bt_icon(self, mac):
        return "audio-card"

    def run(self, *cmd, timeout=15, sudo=False):
        self.calls.append(cmd)
        if cmd[:2] == ("pactl", "get-default-sink"):
            return self.sink
        if cmd[:2] == ("bluetoothctl", "info"):
            return ("Icon: audio-card\nTrusted: " + ("yes" if getattr(self, "trusted", True) else "no")
                    + "\nConnected: " + ("yes" if cmd[2] in self.connected else "no"))
        if cmd[:2] == ("bluetoothctl", "disconnect"):
            self.connected.pop(cmd[2], None)
            return ""
        if "connect" in cmd:
            if self.fail:
                raise self.CmdError("Failed to connect")
            self.connected[cmd[-1]] = "JBL Charge 3"
        return ""

    def audio_status(self):
        bt = [{"name": "bluez_output.AA_BB_CC_DD_EE_FF.1"}] if self.connected else []
        return {"sinks": bt + [{"name": "alsa_output.jack"}]}

    def audio_output(self, sink):
        self.sink = sink


def test_bt_speaker_autoreconnect(tmp_path, monkeypatch):
    import dmxbox.btspeaker as bs
    monkeypatch.setattr(bs.time, "sleep", lambda s: None)
    fake = _FakeBT()
    w = bs.SpeakerWatch(tmp_path / "speaker.json", sysmod=fake)
    fake.trusted = False
    w.tick()
    assert w.info()["connected"] and w.info()["name"] == "JBL Charge 3" and w.state["want_output"]
    assert ("bluetoothctl", "trust", "AA:BB:CC:DD:EE:FF") in fake.calls
    fake.trusted = True
    # pripojený reproduktor sa NIKDY znova nepripája (to rozbíjalo A2DP: „Device or resource busy“)
    fake.calls.clear()
    for _ in range(5):
        w.tick()
    assert not any("connect" in c for c in fake.calls)
    # výpadok: najprv čaká (reproduktor sa môže pripojiť sám) …
    fake.connected.clear(); fake.sink = "alsa_output.jack"; fake.calls.clear()
    w.tick()
    assert w.info()["reconnecting"] and not any(c[-2:-1] == ("connect",) for c in fake.calls)
    # … pripojí sa sám počas čakania → box nič nerobí
    fake.connected["AA:BB:CC:DD:EE:FF"] = "JBL Charge 3"; w.tick()
    assert w.info()["connected"] and not any("--timeout" in c for c in fake.calls)
    # výpadok a po čakaní sa nepripojil → jeden pokus, overený, zvuk späť
    fake.connected.clear(); fake.sink = "alsa_output.jack"; fake.calls.clear()
    w.GRACE_S = 0
    w.tick(); w.tick()
    assert sum(1 for c in fake.calls if "--timeout" in c) == 1
    assert w.info()["connected"] and w.info()["reconnects"] == 1 and fake.sink.startswith("bluez")
    # ručné odpojenie v appke → nenaťahovať späť
    w.manual_disconnect("AA:BB:CC:DD:EE:FF"); fake.connected.clear(); fake.calls.clear()
    w.tick()
    assert not any("connect" in c for c in fake.calls) and w.info()["paused"]
    w.manual_connect("AA:BB:CC:DD:EE:FF")
    # vypnuté auto pripojenie → nič
    w.set_auto(False); w.tick()
    assert not any("connect" in c for c in fake.calls)
    w2 = bs.SpeakerWatch(tmp_path / "speaker.json", sysmod=fake)
    assert w2.info()["auto"] is False and w2.info()["mac"] == "AA:BB:CC:DD:EE:FF"
    # neúspech: ostáva „pripájam“, chyba v stave
    w2.set_auto(True); w2.GRACE_S = 0; fake.fail = True; w2.tick(); w2.tick()
    assert w2.info()["reconnecting"] and "Failed" in w2.info()["error"]
    w2.forget("AA:BB:CC:DD:EE:FF")
    assert w2.info()["mac"] is None


def test_bt_speaker_not_chased_when_output_is_cable(tmp_path, monkeypatch):
    import dmxbox.btspeaker as bs
    monkeypatch.setattr(bs.time, "sleep", lambda s: None)
    fake = _FakeBT()
    fake.OUTPUT_HOOKS = []
    w = bs.SpeakerWatch(tmp_path / "speaker.json", sysmod=fake)
    assert fake.OUTPUT_HOOKS == [w.output_changed]
    w.tick()
    assert w.info()["in_use"]
    # scenár AirPlay → výstup USB karta: reproduktor vypnutý sa nenaháňa
    w.output_changed("alsa_output.usb-C-Media.analog-stereo")
    fake.connected.clear(); fake.sink = "alsa_output.usb"; fake.calls.clear(); w.GRACE_S = 0
    w.tick(); w.tick()
    assert not any("connect" in c for c in fake.calls) and not w.info()["reconnecting"]
    assert w.info()["in_use"] is False
    # späť na BT výstup → znova sa stráži
    w.output_changed("bluez_output.AA_BB_CC_DD_EE_FF.1")
    w.tick(); w.tick()
    assert any("--timeout" in c for c in fake.calls)


def test_bt_speaker_switch_to_other_speaker(tmp_path, monkeypatch):
    import dmxbox.btspeaker as bs
    monkeypatch.setattr(bs.time, "sleep", lambda s: None)
    fake = _FakeBT()
    w = bs.SpeakerWatch(tmp_path / "speaker.json", sysmod=fake)
    w.tick()                                           # HONOR (AA:…) pripojený
    # HONOR vypnutý, pripojený JBL → nový cieľ, starý sa nenaháňa
    fake.connected = {"11:22:33:44:55:66": "JBLemonko"}; fake.calls.clear()
    w.GRACE_S = 0
    w.tick(); w.tick()
    assert w.info()["mac"] == "11:22:33:44:55:66" and w.info()["connected"]
    assert not any(c[-1] == "AA:BB:CC:DD:EE:FF" and "connect" in c for c in fake.calls)
    # ručné pripojenie iného reproduktora v appke = nový cieľ
    w.manual_connect("AA:BB:CC:DD:EE:FF")
    assert w.info()["mac"] == "AA:BB:CC:DD:EE:FF"


def test_bt_speaker_stall_and_half_connection(tmp_path, monkeypatch):
    import dmxbox.btspeaker as bs
    monkeypatch.setattr(bs.time, "sleep", lambda s: None)
    fake = _FakeBT()
    w = bs.SpeakerWatch(tmp_path / "speaker.json", sysmod=fake)
    w.tick(); fake.calls.clear()
    w.CYCLE_MIN_S = 0
    w.kernel_line("Bluetooth: hci0: link tx timeout")
    w.tick()
    assert ("bluetoothctl", "disconnect", "AA:BB:CC:DD:EE:FF") in fake.calls
    assert w.info()["stall_fixes"] == 1
    fake.calls.clear(); w.tick()                       # vyriešené
    assert not any(c[:2] == ("bluetoothctl", "disconnect") for c in fake.calls)
    # polovičné spojenie: Connected: yes, ale žiadny zvukový výstup dlhšie ako HALF_S
    w.CYCLE_MIN_S = 60; w._last_fix = 0.0; w.HALF_S = 0
    orig = fake.audio_status
    fake.audio_status = lambda: {"sinks": [{"name": "alsa_output.jack"}]}
    w.tick(); w.tick()
    assert ("bluetoothctl", "disconnect", "AA:BB:CC:DD:EE:FF") in fake.calls
    fake.calls.clear(); w.tick()                       # najviac raz za minútu
    assert not any(c[:2] == ("bluetoothctl", "disconnect") for c in fake.calls)
    fake.audio_status = orig

def test_session_log(tmp_path):
    import json as _json
    import time as _t
    from fastapi.testclient import TestClient
    from dmxbox.api import create_app
    from dmxbox.nowplaying import Track, stub
    from dmxbox.sessionlog import SessionLog
    box = _box(tmp_path)
    box.nowplaying = stub(); box.nowplaying.track = Track(title="Chimera", artist="Faders", status="playing")
    box.slog = sl = SessionLog(tmp_path / "logs", box, flush_s=999)
    c = TestClient(create_app(box))
    sl.sample(); sl.sample()
    # posuvník master: 3 požiadavky → 1 záznam s poslednou hodnotou; PIN sa nezapíše
    for v in (0.2, 0.5, 0.8):
        c.post("/api/settings", json={"master": v})
    c.post("/api/auth/pin", json={"pin": "", "new_pin": "1234"})
    c.post("/api/system/wifi", json={"ssid": "X", "password": "tajne123"})
    sl._release_actions(force=True)
    sl.flush()
    day = sl.files()[0]["day"]
    recs = SessionLog.read(sl.path_of(day))
    evs = [r["ev"] for r in recs]
    assert "track" in evs and "fx" in evs
    acts = [r for r in recs if r["ev"] == "action"]
    master = [a for a in acts if a["path"] == "/api/settings"]
    assert len(master) == 1 and master[0]["body"]["master"] == 0.8
    raw = sl.path_of(day).read_text()
    assert "1234" not in raw and "tajne123" not in raw and not any(a["path"].startswith("/api/auth") for a in acts)
    # súhrn a sťahovanie cez API
    s = c.get(f"/api/log/summary/{day}").json()
    assert s["tracks"] == 1 and s["actions"] >= 2
    assert c.get(f"/api/log/download/{day}").status_code == 200
    assert c.get("/api/log/download/../../etc").status_code == 404
    assert c.get("/api/log/download-all").content[:2] == b"PK"
    # vypnutie: nič nové sa nezapisuje, nastavenie prežije
    c.post("/api/log/enabled", json={"on": False})
    n = len(SessionLog.read(sl.path_of(day)))
    sl.event("music", bpm=120); sl.flush()
    assert len(SessionLog.read(sl.path_of(day))) == n
    assert SessionLog(tmp_path / "logs").enabled is False


def test_session_log_prune(tmp_path):
    from dmxbox.sessionlog import SessionLog
    d = tmp_path / "logs"; d.mkdir()
    for i in range(1, 20):
        (d / f"2026-10-{i:02d}.jsonl").write_text("x" * 1000)
    sl = SessionLog(d, keep_days=14, max_mb=0.01)
    sl.event("start"); sl.flush()
    files = sorted(p.name for p in d.glob("*.jsonl"))
    assert len(files) <= 14 and sum((d / f).stat().st_size for f in files) <= 0.01 * 1024 * 1024 + 2000


class _FakePW:
    """Simulovaný pactl/systemctl pre AirplayKeep."""
    from dmxbox.system import CmdError

    def __init__(self):
        self.sinks = {"bluez_output.F4.1": "87", "alsa_output.jack": "56"}
        self.modules = {}
        self.default = "bluez_output.F4.1"
        self.calls = []

    def has(self, _):
        return True

    def run(self, *cmd, timeout=15, sudo=False):
        self.calls.append(cmd)
        if cmd[:4] == ("pactl", "list", "short", "sinks"):
            return "\n".join(f"{i}\t{n}\tPipeWire" for n, i in self.sinks.items())
        if cmd[:4] == ("pactl", "list", "short", "modules"):
            return "\n".join(f"{i}\t{n}\t{a}" for i, (n, a) in self.modules.items())
        if cmd[:2] == ("pactl", "load-module"):
            mid = str(500 + len(self.modules))
            self.modules[mid] = (cmd[2], " ".join(cmd[3:]))
            if cmd[2] == "module-null-sink":
                self.sinks["dmxbox_airplay"] = "99"
            return mid
        if cmd[:2] == ("pactl", "unload-module"):
            n, _ = self.modules.pop(cmd[2])
            if n == "module-null-sink":
                self.sinks.pop("dmxbox_airplay", None)
            return ""
        if cmd[:2] == ("pactl", "get-default-sink"):
            return self.default
        if cmd[:2] == ("pactl", "set-default-sink"):
            self.default = cmd[2]
            return ""
        if cmd[:3] == ("systemctl", "--user", "is-active"):
            return "active"
        return ""

    def audio_status(self):
        kind = lambda n: "bluetooth" if n.startswith("bluez") else "jack" if "alsa" in n else "other"
        return {"sinks": [{"name": n, "kind": kind(n)} for n in self.sinks if not n.startswith("dmxbox_")]}


def test_airplay_keep(tmp_path):
    from dmxbox.airplay_keep import AirplayKeep, SINK
    pw = _FakePW()
    dropin = tmp_path / "airplay.service.d" / "dmxbox-keep.conf"
    k = AirplayKeep(tmp_path / "airplay.json", sysmod=pw, dropin=dropin)
    assert k.keep is True                                   # predvolene zapnuté
    k.apply()
    assert SINK in pw.sinks and k.info()["active"]
    assert "PULSE_SINK=dmxbox_airplay" in dropin.read_text()
    assert ("systemctl", "--user", "restart", "airplay") in pw.calls
    # druhý beh: nič nové nevytvára, AirPlay nereštartuje
    pw.calls.clear(); k.apply()
    assert not any(c[:2] == ("pactl", "load-module") for c in pw.calls)
    assert ("systemctl", "--user", "restart", "airplay") not in pw.calls
    # virtuálny výstup sa omylom stal predvoleným → strážca vráti skutočný (BT má prednosť)
    pw.default = SINK; k.apply()
    assert pw.default == "bluez_output.F4.1"
    # po reštarte PipeWire zmizne → znova sa vytvorí
    pw.sinks.pop(SINK); pw.modules.clear(); k.apply()
    assert SINK in pw.sinks
    # vypnutie: moduly preč, drop-in preč, AirPlay reštart; nastavenie prežije
    pw.calls.clear(); k.set_keep(False)
    assert SINK not in pw.sinks and not dropin.exists()
    assert ("systemctl", "--user", "restart", "airplay") in pw.calls
    assert AirplayKeep(tmp_path / "airplay.json", sysmod=pw, dropin=dropin).keep is False


def test_audio_output_skips_airplay_buffer(monkeypatch):
    from dmxbox import system
    calls = []

    def fake_run(*cmd, **kw):
        calls.append(cmd)
        if cmd[:4] == ("pactl", "list", "short", "sinks"):
            return "56\talsa_output.jack\tPipeWire\n99\tdmxbox_airplay\tPipeWire"
        if cmd[:4] == ("pactl", "list", "short", "sink-inputs"):
            return ("71\t99\t12\tPipeWire\n72\t87\t13\tPipeWire\n"      # 71 = AirPlay vo virtuálnom výstupe
                    "73\t56\t14\tPipeWire")                               # 73 už hrá do cieľa

        return ""
    monkeypatch.setattr(system, "run", fake_run)
    monkeypatch.setattr(system, "audio_status", lambda: {"sinks": [{"name": "alsa_output.jack"}]})
    system.audio_output("alsa_output.jack")
    moved = [c[2] for c in calls if c[:2] == ("pactl", "move-sink-input")]
    assert moved == ["72"]


class _FakeAudio:
    from dmxbox.system import CmdError

    def __init__(self):
        self.vol, self.muted, self.calls = 0.57, False, []

    def has(self, _):
        return True

    def run(self, *cmd, timeout=15, sudo=False):
        self.calls.append(cmd)
        if cmd[:2] == ("wpctl", "get-volume"):
            return f"Volume: {self.vol:.2f}" + (" [MUTED]" if self.muted else "")
        if cmd[:2] == ("wpctl", "set-volume"):
            arg = cmd[-1]
            if arg.endswith(("+", "-")):
                d = int(arg[:-2]) / 100
                self.vol = min(1.0, self.vol + d) if arg.endswith("+") else max(0.0, self.vol - d)
            else:
                self.vol = int(arg[:-1]) / 100
        if cmd[:2] == ("wpctl", "set-mute"):
            self.muted = (not self.muted) if cmd[-1] == "toggle" else cmd[-1] == "1"
        if cmd[:2] == ("busctl", "--user") and getattr(self, "no_mpris", False):
            raise self.CmdError("No such interface")
        return ""

    def audio_status(self):
        return {"sinks": [{"name": "bluez_output.X.1", "kind": "bluetooth", "label": "Bluetooth reproduktor",
                           "description": "HONOR CHOICE Speaker Pro", "default": True}]}

    def spotify_status(self):
        return {"active": False}


def test_player(tmp_path):
    from fastapi.testclient import TestClient
    from dmxbox.api import create_app
    from dmxbox.nowplaying import Track, stub
    from dmxbox.player import Player
    box = _box(tmp_path)
    box.nowplaying = stub()
    fa = _FakeAudio()
    box.player = pl = Player(box, sysmod=fa)
    pl.refresh()
    i = pl.info()
    assert i["volume"] == 57 and i["output"] == "HONOR CHOICE Speaker Pro" and i["source"] is None and not i["can_pause"]
    # hlasitosť: krok aj priama hodnota
    assert pl.volume(step=5)["volume"] == 62
    assert pl.volume(value=30)["volume"] == 30
    # bez ovládateľného zdroja → stlmenie
    assert pl.toggle()["muted"] is True
    assert pl.volume(step=5)["muted"] is False                 # zmena hlasitosti zvuk zapne
    # AirPlay: pauza cez MPRIS
    ap = box.nowplaying.airplay
    ap.playing, ap.track = True, Track(title="Chimera", status="playing", source="iPad")
    i = pl.info()
    assert i["source"] == "airplay" and i["device"] == "iPad" and i["can_pause"] and i["playing"]
    i = pl.toggle()
    assert ("busctl", "--user", "call", "org.mpris.MediaPlayer2.ShairportSync", "/org/mpris/MediaPlayer2",
            "org.mpris.MediaPlayer2.Player", "Pause") in fa.calls and i["playing"] is False
    # Bluetooth zdroj: AVRCP
    ap.playing = False
    box.nowplaying.track = Track(title="X", status="playing", source="Mobil", path="/org/bluez/hci0/dev_AA/player0")
    pl.toggle()
    assert ("busctl", "--system", "call", "org.bluez", "/org/bluez/hci0/dev_AA/player0",
            "org.bluez.MediaPlayer1", "Pause") in fa.calls
    # API: AirPlay bez MPRIS → stlmí box
    ap.playing, ap.track = True, Track(title="Y", status="playing")
    fa.no_mpris = True; fa.muted = False
    c = TestClient(create_app(box))
    r = c.post("/api/player/toggle").json()
    assert r["fallback"] == "mute" and fa.muted
    assert c.post("/api/player/volume", json={"step": -5}).status_code == 200


def test_bt_adapter_status(tmp_path):
    from dmxbox.system import bt_adapter_status
    sysfs = tmp_path / "sys"
    uart = sysfs / "devices/platform/soc/serial0/serial0-0/bluetooth/hci0"
    usb = sysfs / "devices/platform/soc/usb/usb1/1-1/1-1.3/1-1.3:1.0/bluetooth/hci0"
    cls = sysfs / "class/bluetooth"; cls.mkdir(parents=True)
    usbdev = sysfs / "bus/usb/devices/1-1.3"; usbdev.mkdir(parents=True)
    (usbdev / "bDeviceClass").write_text("e0\n")
    cfg = tmp_path / "config.txt"; bl = tmp_path / "dmxbox-bt.conf"
    # dongle aktívny, vstavaný vypnutý
    usb.mkdir(parents=True); (cls / "hci0").mkdir(); (cls / "hci0" / "device").symlink_to(usb.parent.parent)
    cfg.write_text("[all]\ndtoverlay=disable-bt\n")
    st = bt_adapter_status(sysfs, cfg, bl)
    assert st["current"] == "dongle" and st["configured"] == "dongle" and st["dongle_present"] and not st["pending"]
    # nastavené na vstavaný, ešte bez reštartu → pending
    cfg.write_text("[all]\n#dtoverlay=disable-bt\n"); bl.write_text("blacklist btusb\n")
    st = bt_adapter_status(sysfs, cfg, bl)
    assert st["configured"] == "builtin" and st["pending"]
    # po reštarte: beží vstavaný (UART)
    (cls / "hci0" / "device").unlink(); uart.mkdir(parents=True); (cls / "hci0" / "device").symlink_to(uart.parent.parent)
    st = bt_adapter_status(sysfs, cfg, bl)
    assert st["current"] == "builtin" and not st["pending"]


def test_bt_connect_rescans_forgotten_device(monkeypatch):
    from dmxbox import system
    calls, seen = [], {"known": False}

    def fake_run(*cmd, **kw):
        calls.append(cmd)
        if cmd[:2] == ("bluetoothctl", "info"):
            if not seen["known"]:
                raise system.CmdError("Device F4:4E:FC:33:A4:B0 not available")
            return "Name: HONOR"
        if "scan" in cmd:
            seen["known"] = True
        return ""
    monkeypatch.setattr(system, "run", fake_run)
    system.bt_connect("F4:4E:FC:33:A4:B0")
    names = [c[3] if c[1] == "--timeout" else c[1] for c in calls if c[0] == "bluetoothctl"]
    assert names.index("scan") < names.index("pair") < names.index("connect")
    # nenájde ani po hľadaní → zrozumiteľná chyba
    seen["known"] = False
    monkeypatch.setattr(system, "run", lambda *c, **k: (_ for _ in ()).throw(system.CmdError("not available"))
                        if c[:2] == ("bluetoothctl", "info") else "")
    import pytest as _p
    with _p.raises(system.CmdError, match="režimu párovania"):
        system.bt_connect("F4:4E:FC:33:A4:B0")


def test_udmx_send_changes_retry_and_reset(monkeypatch):
    import dmxbox.dmx_out as dm
    monkeypatch.setattr(dm.time, "sleep", lambda s: None)

    class FakeUSB:
        def __init__(self):
            self.calls, self.fail_every, self.n, self.resets = [], 0, 0, 0
            self.always_fail = False

        def ctrl_transfer(self, rt, req, n, start, data, timeout=100):
            self.n += 1
            if self.always_fail or (req == 2 and getattr(self, "range_fail", False)):
                raise OSError(75, "Overflow")
            self.calls.append((start, bytes(data)) if req == 2 else ("single", start, n))

        def reset(self):
            self.resets += 1

    out = dm.DMXOut(driver="udmx", channels=40)
    usb_ = FakeUSB()
    out.dev.dev = usb_
    out.dev.open = lambda: (setattr(out.dev, "dev", usb_) or True)
    out.connected = True
    frame = bytearray(40)
    out._write(bytes(frame))
    assert len(usb_.calls) == 5                        # prvý rámec celý (5 × 8 kanálov)
    usb_.calls.clear(); frame[10] = 200
    out._write(bytes(frame))
    assert usb_.calls == [(8, bytes(frame[8:16]))]     # potom len zmenený kúsok
    usb_.calls.clear(); out._write(bytes(frame))
    assert usb_.calls == []                            # bez zmeny nič
    # Pi 3: rozsahy (req 2) zlyhávajú, jednotlivé kanály (req 1) prechádzajú → svetlá idú ďalej
    usb_.range_fail = True; frame[0] = 1; frame[39] = 9; out._full_at = 0; usb_.calls.clear()
    for _ in range(10):
        frame[5] = (frame[5] + 7) % 256
        out._write(bytes(frame))
    assert out.connected and usb_.resets == 0 and out.dev.single_until > 0
    assert ("single", 5, frame[5]) in usb_.calls
    usb_.range_fail = False
    # trvalá chyba: po 5 rámcoch reset a odpojenie
    usb_.always_fail = True; out._sent = None
    for _ in range(5):
        out._write(bytes(frame)); out._sent = None
    assert usb_.resets == 1 and not out.connected


def test_moving_head_floor_mount(tmp_path):
    import time as _t
    from fastapi.testclient import TestClient
    from dmxbox.api import create_app
    from dmxbox.fixtures import ROOT, RigStore
    box = _box(tmp_path)
    box.rig_store = RigStore(tmp_path / "rig.yaml", ROOT / "rig.default.yaml")
    c = TestClient(create_app(box))
    a = box.analyzer.snapshot()
    box.store.update(auto=False, move_fx="sweep")
    h = box.engine.rig["movinghead"]
    f1 = box.engine.compute(a, _t.monotonic())
    pan1, tilt1 = f1[h.addr("pan") - 1], f1[h.addr("tilt") - 1]
    assert h.mount == "ceiling"
    assert c.put("/api/rig/fixture/movinghead", json={"mount": "zle"}).status_code == 400
    r = c.put("/api/rig/fixture/movinghead", json={"mount": "floor"})
    assert r.status_code == 200, r.text
    h = box.engine.rig["movinghead"]
    assert h.mount == "floor"
    assert any(e.get("mount") == "floor" for e in r.json()["fixtures"])
    # otočenie: rovnaká poloha efektu → zrkadlová DMX hodnota (tilt v rámci limitov 40–200)
    assert h.aim("pan", 0.2) == 255 - h.aim("pan", 0.8) or abs(h.aim("pan", 0.2) - (255 - h.aim("pan", 0.8))) <= 1
    lo, hi = h.FLOOR_TILT                       # na zemi: pás okolo zvislice, nie limity zavesenej hlavy
    assert h.aim("tilt", 0.0) == hi and h.aim("tilt", 1.0) == lo
    assert abs(h.aim("tilt", 0.5) - 177) <= 1
    assert c.get("/api/fixtures").json()["movinghead"]["mount"] == "floor"


def test_static_no_cache(tmp_path):
    from fastapi.testclient import TestClient
    from dmxbox.api import create_app
    c = TestClient(create_app(_box(tmp_path)))
    r = c.get("/style.css")
    assert r.status_code == 200 and r.headers.get("cache-control") == "no-cache"
    assert "no-cache" not in c.get("/api/state").headers.get("cache-control", "")


def test_rig_live_and_mute(tmp_path):
    import time as _t
    from fastapi.testclient import TestClient
    from dmxbox.api import create_app
    box = _box(tmp_path)
    c = TestClient(create_app(box))
    box.store.update(auto=False, color_fx="color_step", master=1.0)
    f = box.engine.compute(box.analyzer.snapshot(), _t.monotonic())
    box.out.last = bytes(f)
    live = {x["id"]: x for x in c.get("/api/rig/live").json()["fixtures"]}
    assert set(live) >= {"parbar", "movinghead", "belka"}
    p = live["parbar"]
    assert p["start"] == 1 and p["color"].startswith("#") and 0 <= p["level"] <= 1 and not p["muted"]
    assert "pan" in live["movinghead"]["info"] and "tilt" in live["movinghead"]["info"]
    # STOP: kanály svetla na 0, hlava drží pan/tilt
    r = c.post("/api/rig/mute/parbar", json={"on": True})
    assert r.status_code == 200
    assert c.post("/api/rig/mute/movinghead", json={"on": True}).status_code == 200
    f = box.engine.compute(box.analyzer.snapshot(), _t.monotonic())
    pb, h = box.engine.rig["parbar"], box.engine.rig["movinghead"]
    assert all(f[pb.start - 1 + i] == 0 for i in range(pb.footprint))
    assert f[h.addr("dimmer") - 1] == 0 and f[h.addr("tilt") - 1] > 0
    held = (f[h.addr("pan") - 1], f[h.addr("tilt") - 1])
    box.store.update(move_fx="snap")                   # aj keď sa efekt hýbe, hlava stojí
    for k in range(1, 6):
        f2 = box.engine.compute(box.analyzer.snapshot(), _t.monotonic() + k * 0.7)
        assert (f2[h.addr("pan") - 1], f2[h.addr("tilt") - 1]) == held
    box.out.last = bytes(f)
    live = {x["id"]: x for x in c.get("/api/rig/live").json()["fixtures"]}
    assert live["parbar"]["muted"] and not live["parbar"]["active"] and live["parbar"]["level"] == 0
    # PLAY: späť do show
    c.post("/api/rig/mute/parbar", json={"on": False})
    assert "parbar" not in box.engine.muted
    assert c.post("/api/rig/mute/nic", json={"on": True}).status_code == 404


def test_frame_size_follows_rig(tmp_path):
    from fastapi.testclient import TestClient
    from dmxbox.api import create_app
    from dmxbox.fixtures import ROOT, RigStore, frame_size
    assert frame_size(0) == 8 and frame_size(36) == 40 and frame_size(46) == 48 and frame_size(600) == 512
    box = _box(tmp_path)
    box.rig_store = RigStore(tmp_path / "rig.yaml", ROOT / "rig.default.yaml")
    c = TestClient(create_app(box))
    st = c.get("/api/rig").json()
    assert st["usb_hint"] == 40 and "dongle_limit" not in st
    ents = st["fixtures"]
    last = max((e for e in ents if e["enabled"]), key=lambda e: e["end"])
    r = c.put(f"/api/rig/fixture/{last['id']}", json={"address": 60})
    assert r.status_code == 200, r.text
    end = 60 + last["footprint"] - 1
    assert box.out.channels == frame_size(end) and r.json()["frame"] == frame_size(end)
    assert "512" in (r.json().get("warning") or "")
