"""FastAPI: REST príkazy, WebSocket so stavom, servuje PWA z web/."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import ROOT
from .effects.color import COLOR_FX, PALETTES
from .effects.movement import MOVE_FX


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


def create_app(box) -> FastAPI:
    """`box` má atribúty store, analyzer, engine, out, line_in."""
    app = FastAPI(title="DMX-BOX", version="0.1.0")
    web = ROOT / "web"

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
            "engine": {"color_fx": st.color_fx, "move_fx": st.move_fx, "idle": st.idle},
            "dmx": {"driver": box.out.driver, "connected": box.out.connected,
                    "frames": box.out.frames_sent},
            "line_in": box.line_in.on,
            "fog": {"on": box.engine.fog.status.on, "ready": box.engine.fog.status.ready,
                    "cooldown": round(box.engine.fog.status.cooldown_left, 1),
                    "present": "fog" in box.engine.rig},
        }

    @app.get("/api/state")
    def get_state():
        data = snapshot()
        data["catalog"] = {"color_fx": list(COLOR_FX), "move_fx": list(MOVE_FX),
                           "palettes": list(PALETTES)}
        data["presets"] = sorted(int(k) for k in box.store.presets)
        return data

    @app.get("/api/dmx")
    def get_dmx():
        return {"channels": list(box.out.last)}

    @app.get("/api/fixtures")
    def get_fixtures():
        """Kanálové mapy pre virtuálne svetlá (web/viz.html)."""
        return {k: {"name": f.name, "start": f.start, "channels": f.channels,
                    "ranges": f.ranges, "values": f.values}
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
        await sock.accept()
        try:
            while True:
                a = box.analyzer.snapshot()
                await sock.send_json({"ch": list(box.out.last), "bpm": round(a.bpm, 1),
                                      "silent": a.silent})
                await asyncio.sleep(0.033)
        except (WebSocketDisconnect, RuntimeError):
            pass

    @app.get("/")
    def index():
        return FileResponse(web / "index.html")

    if web.exists():
        app.mount("/", StaticFiles(directory=web), name="web")
    return app
