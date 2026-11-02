"""FastAPI: REST príkazy, WebSocket so stavom, servuje PWA z web/."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import scenario as scen
from .auth import COOKIE, MAX_AGE, Auth, PinError
from . import fixtures as fxlib
from . import system
from .config import ROOT
from .effects.color import COLOR_FX, PALETTES
from .effects.movement import MOVE_FX
from .genre import STYLE_NAMES
from .styles import STYLE_CHOICES, catalog as style_catalog

log = logging.getLogger("dmxbox.api")


class Patch(BaseModel):
    model_config = {"extra": "allow"}


class FxBody(BaseModel):
    wheel: int
    fx: str


class OnBody(BaseModel):
    on: bool
    bars: int | None = None


class ValueBody(BaseModel):
    value: float


class BpmBody(BaseModel):
    bpm: float | None = None
    factor: float | None = None


class WifiBody(BaseModel):
    ssid: str
    password: str = ""


class VolumeBody(BaseModel):
    value: int | None = None
    step: int | None = None


class MacBody(BaseModel):
    mac: str


class TextBody(BaseModel):
    value: str


class ActionLog:
    """Ručné zásahy z appky (POST/PUT/DELETE na /api) → záznam prevádzky. Čistý ASGI, telo požiadavky nemení."""

    def __init__(self, app, box):
        self.app, self.box = app, box

    async def __call__(self, scope, receive, send):
        sl = getattr(self.box, "slog", None)
        if (sl is None or scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "DELETE")
                or not scope["path"].startswith("/api/")):
            await self.app(scope, receive, send)
            return
        chunks: list[bytes] = []
        status = {"code": 0}

        async def recv():
            msg = await receive()
            if msg["type"] == "http.request" and sum(map(len, chunks)) < 20000:
                chunks.append(msg.get("body", b""))
            return msg

        async def snd(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
            await send(msg)

        await self.app(scope, recv, snd)
        try:
            sl.action(scope["method"], scope["path"], b"".join(chunks), status["code"])
        except Exception:  # noqa: BLE001
            pass


def _cmd(fn, *args):
    """Systémový príkaz → HTTP 400 so zrozumiteľnou správou."""
    try:
        res = fn(*args)
    except system.CmdError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "result": res}


class PinBody(BaseModel):
    pin: str
    new_pin: str | None = None
    on: bool | None = None


PUBLIC = {"/lock.html", "/lock.js", "/style.css", "/start.css", "/icon.svg", "/manifest.json", "/sw.js"}


class Captive:
    """V hotspote presmeruje cudzie domény (kontrola pripojenia mobilu) na vstupnú obrazovku.

    Telefón tak po pripojení na Wi-Fi DMX-BOX sám otvorí appku (captive portal).
    DNS v hotspote smeruje všetko na 10.42.0.1 (install.sh → dnsmasq-shared.d).
    """

    def __init__(self):
        self.hostnames = {"localhost", socket.gethostname().lower(), socket.gethostname().lower() + ".local"}
        self._mode, self._checked = "none", 0.0

    def hotspot(self) -> bool:
        if time.monotonic() - self._checked > 10:
            self._checked = time.monotonic()
            try:
                self._mode = system.wifi_status()["mode"] if system.has("nmcli") else "none"
            except Exception:  # noqa: BLE001 – stav siete nesmie zhodiť web
                self._mode = "none"
        return self._mode == "hotspot"

    def foreign(self, host: str) -> bool:
        h = host.rsplit(":", 1)[0].strip("[]").lower() if host.count(":") <= 1 else host.lower()
        if h in self.hostnames or h.endswith(".local"):
            return False
        try:
            ipaddress.ip_address(h)
            return False
        except ValueError:
            return True


def create_app(box) -> FastAPI:
    """`box` má atribúty store, analyzer, engine, out, line_in."""
    app = FastAPI(title="DMX-BOX", version="0.3.0")
    web = ROOT / "web"
    captive = Captive()
    auth: Auth = getattr(box, "auth", None) or Auth(None)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host", "")
        if host and captive.foreign(host) and captive.hotspot():
            return RedirectResponse("http://10.42.0.1/", status_code=302)
        path = request.url.path
        if (auth.required and path not in PUBLIC and not path.startswith("/api/auth")
                and not auth.valid(request.cookies.get(COOKIE))):
            if path.startswith("/api"):
                return JSONResponse({"detail": "zadaj PIN"}, status_code=401)
            nxt = path if path.startswith("/") and not path.startswith("//") else "/"
            return RedirectResponse(f"/lock.html?next={nxt}", status_code=302)
        return await call_next(request)

    def logged_in(resp: JSONResponse) -> JSONResponse:
        resp.set_cookie(COOKIE, auth.token(), max_age=MAX_AGE, httponly=True, samesite="lax")
        return resp

    # --- PIN ochrana -----------------------------------------------------------------
    @app.get("/api/auth")
    def auth_state(request: Request):
        return {"required": auth.required, "has_pin": auth.has_pin,
                "ok": auth.valid(request.cookies.get(COOKIE))}

    @app.post("/api/auth/login")
    def auth_login(body: PinBody, request: Request):
        try:
            ok = auth.check_pin(body.pin, request.client.host if request.client else "")
        except PinError as e:
            raise HTTPException(429, str(e)) from e
        if not ok:
            raise HTTPException(401, "nesprávny PIN")
        return logged_in(JSONResponse({"ok": True}))

    @app.post("/api/auth/pin")
    def auth_set_pin(body: PinBody, request: Request):
        """Nastaviť alebo zmeniť PIN. Existujúci PIN treba potvrdiť (pin), nový je new_pin."""
        client = request.client.host if request.client else ""
        try:
            if auth.has_pin and not auth.check_pin(body.pin, client):
                raise HTTPException(401, "nesprávny súčasný PIN")
            auth.set_pin(body.new_pin or "")
        except PinError as e:
            raise HTTPException(400, str(e)) from e
        return logged_in(JSONResponse({"ok": True, "required": auth.required}))

    @app.post("/api/auth/required")
    def auth_required(body: PinBody, request: Request):
        """Zapnúť/vypnúť vyžadovanie PINu – vždy s potvrdením PINom."""
        try:
            if not auth.check_pin(body.pin, request.client.host if request.client else ""):
                raise HTTPException(401, "nesprávny PIN")
            auth.set_required(bool(body.on))
        except PinError as e:
            raise HTTPException(400, str(e)) from e
        return logged_in(JSONResponse({"ok": True, "required": auth.required}))

    @app.post("/api/auth/logout")
    def auth_logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE)
        return resp

    _bta = {"t": 0.0, "v": None}

    def bt_adapter_cached():
        if time.monotonic() - _bta["t"] > 10:
            _bta["t"] = time.monotonic()
            try:
                _bta["v"] = system.bt_adapter_status()
            except Exception:  # noqa: BLE001
                _bta["v"] = None
        return _bta["v"]

    sysstats = system.SysStats()
    box.sysstats = sysstats                     # zdieľané so záznamom prevádzky

    def snapshot() -> dict[str, Any]:
        a = box.analyzer.snapshot()
        st = box.engine.status
        return {
            "settings": asdict(box.store.get()),
            "audio": {"bpm": round(a.bpm, 1), "confident": a.bpm_confident,
                      "phase": round(a.beat_phase, 3), "beat": a.beat_count,
                      "bass": round(a.bass, 3), "mid": round(a.mid, 3),
                      "high": round(a.high, 3), "level": round(a.level, 3),
                      "silent": a.silent},
            "engine": {"color_fx": st.color_fx, "move_fx": st.move_fx, "idle": st.idle,
                       "style": st.style, "style_auto": st.style_auto, "section": st.section},
            "music": {"style": a.style, "name": STYLE_NAMES.get(a.style, a.style),
                      "confidence": round(a.style_confidence, 2),
                      "scores": {k: round(v, 2) for k, v in a.style_scores.items()},
                      "section": a.section, "drops": a.drop_count,
                      "build": round(a.build_progress, 2)},
            "dmx": {"driver": box.out.driver, "connected": box.out.connected,
                    "frames": box.out.frames_sent},
            "line_in": box.line_in.on,
            "viz": {"l": [int(x * 99) for x in a.viz_l], "r": [int(x * 99) for x in a.viz_r]},   # 0–99, menšie správy
            "track": box.nowplaying.track.as_dict() if getattr(box, "nowplaying", None) else None,
            "sys": sysstats.get(),
            "speaker": box.speaker.info() if getattr(box, "speaker", None) else None,
            "airkeep": box.airkeep.info() if getattr(box, "airkeep", None) else None,
            "player": box.player.info() if getattr(box, "player", None) else None,
            "bt_adapter": bt_adapter_cached(),
            "fog": {"on": box.engine.fog.status.on, "ready": box.engine.fog.status.ready,
                    "cooldown": round(box.engine.fog.status.cooldown_left, 1),
                    "present": "fog" in box.engine.rig},
        }

    @app.get("/api/state")
    def get_state():
        data = snapshot()
        data["catalog"] = {"color_fx": list(COLOR_FX), "move_fx": list(MOVE_FX),
                           "palettes": list(PALETTES), "styles": style_catalog()}
        data["presets"] = sorted(int(k) for k in box.store.presets)
        return data

    @app.get("/api/dmx")
    def get_dmx():
        return {"channels": list(box.out.last)}

    @app.get("/api/fixtures")
    def get_fixtures():
        """Kanálové mapy pre virtuálne svetlá (web/viz.html)."""
        return {k: {"name": f.name, "start": f.start, "channels": f.channels,
                    "ranges": f.ranges, "values": f.values, "label": f.label, "type": f.type,
                    "fns": f.fns, "position": f.position, "profile": f.profile,
                    "known": k in box.engine.KNOWN}
                for k, f in box.engine.rig.fx.items()}

    @app.post("/api/settings")
    def patch_settings(body: Patch):
        data = body.model_dump()
        if "color_fx" in data and data["color_fx"] not in COLOR_FX:
            raise HTTPException(400, "neznámy color_fx")
        if "move_fx" in data and data["move_fx"] not in MOVE_FX:
            raise HTTPException(400, "neznámy move_fx")
        if "palette" in data and data["palette"] not in PALETTES:
            raise HTTPException(400, "neznáma paleta")
        if "style" in data and data["style"] not in STYLE_CHOICES:
            raise HTTPException(400, "neznámy štýl")
        if "line_in" in data:
            box.line_in.set(bool(data["line_in"]))
        return asdict(box.store.update(**data))

    @app.post("/api/fx")
    def set_fx(body: FxBody):
        key = "color_fx" if body.wheel == 1 else "move_fx"
        return patch_settings(Patch(**{key: body.fx, "auto": False}))

    @app.post("/api/mod")
    def set_mod(body: Patch):
        allowed = {k: v for k, v in body.model_dump().items() if k in ("speed", "size", "fade")}
        return asdict(box.store.update(**allowed))

    @app.post("/api/master")
    def set_master(body: ValueBody):
        return asdict(box.store.update(master=max(0.0, min(1.0, body.value))))

    @app.post("/api/blackout")
    def set_blackout(body: OnBody):
        return asdict(box.store.update(blackout=body.on))

    @app.post("/api/strobe")
    def set_strobe(body: OnBody):
        return asdict(box.store.update(strobe=body.on))

    @app.post("/api/fog")
    def set_fog(body: OnBody):
        return asdict(box.store.update(fog=body.on))

    @app.post("/api/auto")
    def set_auto(body: OnBody):
        return asdict(box.store.update(auto=body.on, auto_bars=body.bars))

    @app.post("/api/tap")
    def tap():
        box.analyzer.tap()
        return {"ok": True}

    @app.post("/api/bpm")
    def set_bpm(body: BpmBody):
        if body.factor:
            box.analyzer.scale_bpm(body.factor)
        else:
            box.analyzer.set_bpm_override(body.bpm)  # None = späť na auto
        return {"bpm": box.analyzer.snapshot().bpm}

    @app.post("/api/preset/{n}")
    def load_preset(n: int):
        s = box.store.load_preset(n)
        if s is None:
            raise HTTPException(404, "preset je prázdny")
        return asdict(s)

    @app.put("/api/preset/{n}")
    def save_preset(n: int):
        if not 1 <= n <= 50:
            raise HTTPException(400, "slot 1–50")
        return box.store.save_preset(n)

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        if not auth.allowed(sock.cookies.get(COOKIE)):
            await sock.close(code=4401)
            return
        await sock.accept()
        try:
            while True:
                await sock.send_json(snapshot())
                await asyncio.sleep(0.05)   # 20× za sekundu
        except (WebSocketDisconnect, RuntimeError):
            pass

    @app.websocket("/ws/dmx")
    async def ws_dmx(sock: WebSocket):
        """DMX rámec tak, ako ide do svetiel (aj s light delay), ~30× za sekundu."""
        if not auth.allowed(sock.cookies.get(COOKIE)):
            await sock.close(code=4401)
            return
        await sock.accept()
        try:
            while True:
                a = box.analyzer.snapshot()
                st = box.engine.status
                await sock.send_json({"ch": list(box.out.last), "bpm": round(a.bpm, 1),
                                      "silent": a.silent, "style": STYLE_NAMES.get(st.style, st.style),
                                      "section": st.section})
                await asyncio.sleep(0.033)
        except (WebSocketDisconnect, RuntimeError):
            pass

    # --- scenáre (vstupná obrazovka) -------------------------------------------
    @app.get("/api/scenarios")
    def get_scenarios():
        st = box.scenarios
        return {"scenarios": scen.SCENARIOS, "last": st.last if st else None,
                "last_summary": scen.summary(st.last if st else None),
                "current": st.current if st else None}

    @app.post("/api/scenario")
    def set_scenario(body: Patch):
        if box.scenarios is None:
            raise HTTPException(503, "scenáre nie sú dostupné")
        try:
            return scen.apply(box, body.model_dump())
        except system.CmdError as e:
            raise HTTPException(400, str(e)) from e

    # --- systém: Wi-Fi, BT, zvuk, Spotify (bez SSH) ---------------------------------
    @app.get("/api/system")
    def sys_status():
        st = system.status()
        st["dmx"] = {"driver": box.out.driver, "connected": box.out.connected,
                     "fixtures": [f"{f.label} {f.name}".strip() for f in box.engine.rig.fx.values()]}
        return st

    @app.get("/api/system/wifi/scan")
    def wifi_scan():
        return _cmd(system.wifi_scan)

    @app.post("/api/system/wifi")
    def wifi_add(body: WifiBody):
        return _cmd(system.wifi_add, body.ssid, body.password)

    @app.post("/api/system/wifi/connect")
    def wifi_connect(body: WifiBody):
        return _cmd(system.wifi_connect, body.ssid)

    @app.post("/api/system/wifi/delete")
    def wifi_delete(body: WifiBody):
        return _cmd(system.wifi_delete, body.ssid)

    @app.post("/api/system/hotspot")
    def hotspot(body: OnBody):
        return _cmd(system.hotspot_set, body.on)

    @app.post("/api/system/hotspot/auto")
    def hotspot_auto(body: OnBody):
        return _cmd(system.hotspot_auto, body.on)

    @app.post("/api/system/hotspot/password")
    def hotspot_password(body: TextBody):
        return _cmd(system.hotspot_password, body.value)

    @app.post("/api/system/bt/discoverable")
    def bt_discoverable(body: OnBody):
        return _cmd(system.bt_discoverable, body.on)

    @app.get("/api/system/bt/scan")
    def bt_scan():
        return _cmd(system.bt_scan)

    @app.post("/api/system/bt/connect")
    def bt_connect(body: MacBody):
        res = _cmd(system.bt_connect, body.mac)
        if getattr(box, "speaker", None):
            box.speaker.manual_connect(body.mac)
        return res

    @app.post("/api/system/bt/disconnect")
    def bt_disconnect(body: MacBody):
        if getattr(box, "speaker", None):       # ručné odpojenie = nenaťahovať späť
            box.speaker.manual_disconnect(body.mac)
        return _cmd(system.bt_disconnect, body.mac)

    @app.post("/api/system/bt/forget")
    def bt_forget(body: MacBody):
        if getattr(box, "speaker", None):
            box.speaker.forget(body.mac)
        return _cmd(system.bt_forget, body.mac)

    @app.get("/api/system/bt/adapter")
    def bt_adapter():
        return system.bt_adapter_status()

    @app.post("/api/system/bt/adapter")
    def bt_adapter_set(body: TextBody):
        return _cmd(system.bt_adapter_set, body.value)

    @app.post("/api/system/bt/autoreconnect")
    def bt_autoreconnect(body: OnBody):
        if not getattr(box, "speaker", None):
            raise HTTPException(400, "Bluetooth nie je dostupný")
        return {"ok": True, "result": box.speaker.set_auto(body.on)}

    @app.post("/api/system/audio/output")
    def audio_output(body: TextBody):
        res = _cmd(system.audio_output, body.value)
        if box.sources and not box.store.get().ambient:
            box.analyzer.switch_source(box.sources["live"](),
                                       realtime=box.sources.get("live_realtime", False))
        if box.line_in.on:          # loopback presmerovať na nový výstup
            box.line_in.set(False)
            box.line_in.set(True)
        return res

    @app.post("/api/system/audio/volume")
    def audio_volume(body: ValueBody):
        return _cmd(system.audio_volume, int(body.value))

    @app.post("/api/system/airplay")
    def airplay(body: OnBody):
        return _cmd(system.airplay_set, body.on)

    # --- prehrávač (hlasitosť, play/pauza) ---------------------------------------------
    def player():
        pl = getattr(box, "player", None)
        if pl is None:
            raise HTTPException(400, "prehrávač nie je dostupný")
        return pl

    @app.post("/api/player/volume")
    def player_volume(body: VolumeBody):
        return {"ok": True, "result": _cmd(player().volume, body.value, body.step)["result"]}

    @app.post("/api/player/toggle")
    def player_toggle():
        pl = player()
        try:
            return {"ok": True, "result": pl.toggle()}
        except system.CmdError as e:
            # zdroj sa nedal ovládať (napr. AirPlay bez MPRIS) → aspoň stlmiť box
            log.warning("play/pauza zdroja zlyhala (%s) – stlmujem box", e)
            try:
                pl.sys.run("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle", timeout=5)
            except system.CmdError as e2:
                raise HTTPException(400, str(e2)) from e2
            pl.refresh()
            return {"ok": True, "result": pl.info(), "fallback": "mute"}

    @app.post("/api/system/airplay/keep")
    def airplay_keep(body: OnBody):
        if not getattr(box, "airkeep", None):
            raise HTTPException(400, "AirPlay nie je dostupný")
        return {"ok": True, "result": box.airkeep.set_keep(body.on)}

    @app.post("/api/system/spotify")
    def spotify(body: OnBody):
        return _cmd(system.spotify_set, body.on)

    @app.post("/api/system/update")
    def update():
        return _cmd(system.update)

    @app.post("/api/system/restart")
    def restart():
        return _cmd(system.restart_app)

    @app.post("/api/system/power")
    def power(body: TextBody):
        return _cmd(system.power, body.value)

    # --- správa svetiel (Nastavenia boxu → Svetlá) -------------------------------------
    rig_store = getattr(box, "rig_store", None)
    dongle_limit = box.out.channels

    def rig_state(extra: dict | None = None) -> dict:
        profiles = fxlib.load_profiles()
        entries = rig_store.load_entries() if rig_store else []
        fixtures = []
        for e in entries:
            prof = profiles.get(e.get("profile"), {})
            try:
                n = fxlib.footprint_of(e, profiles)
            except fxlib.RigError:
                n = 0
            a = int(e.get("address", 0))
            fixtures.append({**e, "enabled": e.get("enabled", True), "footprint": n, "end": a + n - 1,
                             "model": prof.get("name", e.get("profile")), "type": prof.get("type", "other")})
        return {"fixtures": fixtures, "map": fxlib.channel_map(entries, profiles),
                "errors": fxlib.validate(entries, profiles), "dongle_limit": dongle_limit,
                "profiles": [{"id": p["id"], "name": p["name"], "type": p.get("type", "other"),
                              "user": p.get("user", False), "notes": p.get("notes", ""),
                              "modes": {m: [{"name": c["name"], "fn": c.get("fn", "other"), "value": c.get("value")}
                                            for c in v.get("channels", [])]
                                        for m, v in (p.get("modes") or {}).items()}}
                             for p in profiles.values()],
                "functions": fxlib.FUNCTIONS, "types": fxlib.TYPES, "positions": fxlib.POSITIONS, **(extra or {})}

    def need_store():
        if not rig_store:
            raise HTTPException(503, "správa svetiel nie je dostupná")

    def apply_rig(entries: list[dict]) -> dict:
        try:
            rig_store.save(entries)
        except fxlib.RigError as e:
            raise HTTPException(400, str(e)) from e
        rig = rig_store.build()
        box.engine.rig = rig
        warn = None
        end = max((f.start + f.footprint - 1 for f in rig.fx.values()), default=0)
        if end > box.out.channels:
            box.out.channels = min(512, -(-end // 8) * 8)
        if end > dongle_limit:
            warn = (f"Svetlá siahajú po kanál {end}. Lacný USB-DMX dongle (uDMX) spoľahlivo zvláda asi "
                    f"{dongle_limit} kanálov – ak by svetlá blikali alebo zamŕzali, posuň adresy nižšie.")
        return rig_state({"warning": warn})

    def clean(body: dict, existing: dict | None = None) -> dict:
        e = dict(existing or {})
        for k in ("label", "name", "profile", "mode", "position"):
            if k in body and body[k] is not None:
                e[k] = str(body[k]).strip()
        if "label" in e:
            e["label"] = e["label"].upper()
        if "address" in body:
            try:
                e["address"] = int(body["address"])
            except (TypeError, ValueError) as ex:
                raise HTTPException(400, "adresa musí byť číslo") from ex
        for k in ("enabled", "mirror"):
            if k in body:
                e[k] = bool(body[k])
        if e.get("position") not in fxlib.POSITIONS:
            e["position"] = "center"
        return e

    @app.get("/api/rig")
    def get_rig():
        need_store()
        return rig_state()

    @app.post("/api/rig/check")
    def check_rig(body: Patch):
        """Kontrola bez uloženia (appka ju volá pri písaní adresy)."""
        need_store()
        data = body.model_dump()
        entries = rig_store.load_entries()
        fid = data.get("id")
        cur = next((e for e in entries if e.get("id") == fid), None)
        cand = clean(data, cur)
        cand.setdefault("id", "novy")
        others = [e for e in entries if e.get("id") != fid]
        profiles = fxlib.load_profiles()
        errors = fxlib.validate(others + [cand], profiles)
        try:
            n = fxlib.footprint_of(cand, profiles)
        except fxlib.RigError:
            n = 0
        return {"errors": errors, "footprint": n,
                "free": fxlib.free_address(others, profiles, n) if n else None}

    @app.post("/api/rig/fixture")
    def add_fixture(body: Patch):
        need_store()
        entries = rig_store.load_entries()
        ids = {e["id"] for e in entries}
        n = 1
        while f"fx{n}" in ids:
            n += 1
        e = clean(body.model_dump())
        e["id"] = f"fx{n}"
        e.setdefault("enabled", True)
        return apply_rig(entries + [e])

    @app.put("/api/rig/fixture/{fid}")
    def edit_fixture(fid: str, body: Patch):
        need_store()
        entries = rig_store.load_entries()
        for i, e in enumerate(entries):
            if e.get("id") == fid:
                entries[i] = clean(body.model_dump(), e)
                return apply_rig(entries)
        raise HTTPException(404, "svetlo nenájdené")

    @app.delete("/api/rig/fixture/{fid}")
    def delete_fixture(fid: str):
        need_store()
        entries = rig_store.load_entries()
        rest = [e for e in entries if e.get("id") != fid]
        if len(rest) == len(entries):
            raise HTTPException(404, "svetlo nenájdené")
        return apply_rig(rest)

    def fixture_for(fid: str) -> fxlib.Fixture:
        for e in rig_store.load_entries():
            if e.get("id") == fid:
                try:
                    return fxlib.build_fixture(e, fxlib.load_profiles())
                except fxlib.RigError as ex:
                    raise HTTPException(400, str(ex)) from ex
        raise HTTPException(404, "svetlo nenájdené")

    @app.post("/api/rig/identify/{fid}")
    def identify(fid: str):
        need_store()
        import time as _t
        box.engine.identify = (fixture_for(fid), _t.monotonic() + 4.0)
        return {"ok": True}

    @app.post("/api/rig/test/{fid}")
    def test_channels(fid: str, body: Patch):
        """Test kanálov: svieti len toto svetlo s hodnotami z appky (4 s od poslednej zmeny)."""
        need_store()
        import time as _t
        fx = fixture_for(fid)
        vals = {k: max(0, min(255, int(v))) for k, v in body.model_dump().items() if k in fx.channels}
        box.engine.test = (fx, vals, _t.monotonic() + 4.0)
        return {"ok": True}

    @app.post("/api/rig/test-stop")
    def test_stop():
        box.engine.test = None
        box.engine.identify = None
        return {"ok": True}

    @app.post("/api/rig/profile")
    def add_profile(body: Patch):
        need_store()
        data = body.model_dump()
        old = fxlib.load_profiles().get(data.get("id") or "")
        path = fxlib.user_dir() / f"{data.get('id')}.yaml"
        backup = path.read_text(encoding="utf-8") if old and old.get("user") and path.exists() else None
        try:
            prof = fxlib.save_user_profile(data)
            if backup is not None:               # úprava modelu, ktorý už svetlá používajú
                errs = fxlib.validate(rig_store.load_entries(), fxlib.load_profiles())
                if errs:
                    raise fxlib.RigError("po zmene by sa svetlá prekrývali: " + " · ".join(errs))
        except fxlib.RigError as e:
            if backup is not None:
                path.write_text(backup, encoding="utf-8")
            raise HTTPException(400, str(e)) from e
        if backup is not None:
            box.engine.rig = rig_store.build()
        return rig_state({"created": prof["id"]})

    @app.get("/api/rig/export")
    def export_rig():
        need_store()
        user = {p["id"]: {k: v for k, v in p.items() if k != "user"}
                for p in fxlib.load_profiles().values() if p.get("user")}
        return {"fixtures": rig_store.load_entries(), "profiles": user}

    @app.post("/api/rig/import")
    def import_rig(body: Patch):
        need_store()
        data = body.model_dump()
        for prof in (data.get("profiles") or {}).values():
            try:
                modes = prof.get("modes") or {}
                mode, m = next(iter(modes.items()))
                fxlib.save_user_profile({**prof, "mode": mode, "channels": m.get("channels", [])})
            except (fxlib.RigError, StopIteration, AttributeError) as e:
                raise HTTPException(400, f"model {prof.get('name')}: {e}") from e
        entries = data.get("fixtures")
        if not isinstance(entries, list):
            raise HTTPException(400, "súbor neobsahuje zoznam svetiel")
        return apply_rig(entries)

    # --- záznam prevádzky ------------------------------------------------------------
    def slog():
        sl = getattr(box, "slog", None)
        if sl is None:
            raise HTTPException(400, "záznam prevádzky nebeží")
        return sl

    @app.get("/api/log")
    def log_state():
        sl = getattr(box, "slog", None)
        if sl is None:
            return {"available": False, "enabled": False, "files": []}
        return {"available": True, "enabled": sl.enabled, "files": sl.files()}

    @app.post("/api/log/enabled")
    def log_enabled(body: OnBody):
        slog().set_enabled(body.on)
        return log_state()

    @app.get("/api/log/summary/{day}")
    def log_summary(day: str):
        res = slog().summary(day)
        if res is None:
            raise HTTPException(404, "záznam pre tento deň neexistuje")
        return res

    @app.get("/api/log/download/{day}")
    def log_download(day: str):
        p = slog().path_of(day)
        if p is None:
            raise HTTPException(404, "záznam pre tento deň neexistuje")
        return FileResponse(p, media_type="application/x-ndjson", filename=f"dmxbox-{day}.jsonl")

    @app.get("/api/log/download-all")
    def log_download_all():
        data = slog().zip_all()
        return Response(data, media_type="application/zip",
                        headers={"content-disposition": 'attachment; filename="dmxbox-zaznam.zip"'})

    app.add_middleware(ActionLog, box=box)

    @app.get("/")
    def start():
        return FileResponse(web / "start.html")

    @app.get("/ovladanie")
    def index():
        return FileResponse(web / "index.html")

    if web.exists():
        app.mount("/", StaticFiles(directory=web), name="web")
    return app
