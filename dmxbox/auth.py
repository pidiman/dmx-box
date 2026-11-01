"""PIN ochrana appky.

- PIN (4–8 číslic) sa ukladá len ako hash (PBKDF2-SHA256 so soľou) v security.json.
- Po zadaní PINu dostane zariadenie podpísaný cookie platný 30 dní, takže tablet sa nepýta stále.
- Po 5 zlých pokusoch z jednej adresy je 30 s pauza (proti skúšaniu PINov).
- Zmena PINu zneplatní prihlásenie na ostatných zariadeniach.
- Zabudnutý PIN: na Pi `dmxbox pin reset` (zmaže security.json).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from pathlib import Path

log = logging.getLogger("dmxbox.auth")

COOKIE = "dmxbox_auth"
MAX_AGE = 30 * 24 * 3600
MAX_TRIES, LOCK_S = 5, 30.0
ITER = 120_000


class PinError(ValueError):
    pass


def _hash(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), ITER).hex()


class Auth:
    def __init__(self, path: Path | None):
        self.path = path
        self.lock = threading.Lock()
        self.data = {"required": False, "pin_hash": None, "salt": None, "secret": secrets.token_hex(32)}
        self._fails: dict[str, tuple[int, float]] = {}
        if path is not None:
            try:
                self.data.update(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass

    # --- stav ---------------------------------------------------------------------
    @property
    def has_pin(self) -> bool:
        return bool(self.data.get("pin_hash"))

    @property
    def required(self) -> bool:
        return bool(self.data.get("required")) and self.has_pin

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            self.path.chmod(0o600)
        except OSError as e:
            log.warning("security.json: %s", e)

    # --- PIN ----------------------------------------------------------------------
    def set_pin(self, pin: str) -> None:
        if not (pin.isdigit() and 4 <= len(pin) <= 8):
            raise PinError("PIN musí mať 4–8 číslic")
        with self.lock:
            salt = secrets.token_hex(16)
            self.data.update(pin_hash=_hash(pin, salt), salt=salt, secret=secrets.token_hex(32))
            self._save()

    def set_required(self, on: bool) -> None:
        if on and not self.has_pin:
            raise PinError("najprv nastav PIN")
        with self.lock:
            self.data["required"] = bool(on)
            self._save()

    def check_pin(self, pin: str, client: str = "") -> bool:
        now = time.monotonic()
        n, until = self._fails.get(client, (0, 0.0))
        if now < until:
            raise PinError(f"veľa pokusov, skús o {int(until - now) + 1} s")
        ok = self.has_pin and hmac.compare_digest(_hash(str(pin), self.data["salt"]), self.data["pin_hash"])
        if ok:
            self._fails.pop(client, None)
        else:
            n += 1
            self._fails[client] = (0, now + LOCK_S) if n >= MAX_TRIES else (n, 0.0)
        return ok

    # --- prihlásenie zariadenia (cookie) ---------------------------------------------
    def _sign(self, payload: str) -> str:
        return hmac.new(self.data["secret"].encode(), payload.encode(), hashlib.sha256).hexdigest()

    def token(self) -> str:
        payload = f"{int(time.time())}.{secrets.token_hex(8)}"
        return f"{payload}.{self._sign(payload)}"

    def valid(self, token: str | None) -> bool:
        if not token or token.count(".") != 2:
            return False
        payload, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(self._sign(payload), sig):
            return False
        try:
            issued = int(payload.split(".")[0])
        except ValueError:
            return False
        return time.time() - issued < MAX_AGE

    def allowed(self, token: str | None) -> bool:
        return not self.required or self.valid(token)
