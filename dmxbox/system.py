"""Ovládanie systému z webu: Wi-Fi, hotspot, Bluetooth, zvuk, Spotify, aktualizácia, vypnutie.

Na párty nie je po ruke počítač s SSH, preto všetko, čo robí príkaz `dmxbox`, ide aj cez API.
Príkazy sa volajú bez shellu (argumenty ako zoznam), takže SSID ani heslo nič nevykonajú.
Privilegované príkazy idú cez `sudo -n` podľa /etc/sudoers.d/dmxbox (install.sh).
Mimo Pi (Mac, testy) chýbajúce nástroje vrátia prázdny stav, nie chybu.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .config import ROOT

log = logging.getLogger("dmxbox.system")

HOTSPOT = "dmx-hotspot"
HOTSPOT_SSID = "fajny-dmx-box"     # skutočné SSID sa číta z NetworkManageru
MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$", re.I)


class CmdError(RuntimeError):
    """Chyba príkazu so správou pre používateľa."""


def has(tool: str) -> bool:
    return shutil.which(tool) is not None


def run(*cmd: str, sudo: bool = False, timeout: float = 15) -> str:
    args = ["sudo", "-n", *cmd] if sudo else list(cmd)
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise CmdError(f"{cmd[0]} nie je nainštalovaný") from e
    except subprocess.TimeoutExpired as e:
        raise CmdError(f"{cmd[0]}: vypršal čas") from e
    if p.returncode != 0:
        msg = (p.stderr or p.stdout).strip().splitlines()
        raise CmdError(msg[-1] if msg else f"{cmd[0]} zlyhal ({p.returncode})")
    return p.stdout.strip()


def later(delay: float, *cmd: str, sudo: bool = False) -> None:
    """Spustí príkaz o chvíľu na pozadí (odpoveď HTTP stihne odísť)."""
    def go():
        time.sleep(delay)
        try:
            run(*cmd, sudo=sudo, timeout=60)
        except CmdError as e:
            log.warning("%s: %s", " ".join(cmd), e)
    threading.Thread(target=go, daemon=True).start()


def _split_t(line: str) -> list[str]:
    """nmcli -t: polia oddelené ':', dvojbodka v hodnote je '\\:'."""
    return [p.replace("\\:", ":") for p in re.split(r"(?<!\\):", line)]


# --- Wi-Fi a hotspot ------------------------------------------------------------

def wifi_status() -> dict:
    st = {"available": has("nmcli"), "mode": "none", "ssid": None, "ip": None,
          "saved": [], "hotspot": {"ssid": HOTSPOT_SSID, "password": None, "auto": False,
                                   "ip": "10.42.0.1"}}
    if not st["available"]:
        return st
    try:
        st["hotspot"]["ssid"] = run("nmcli", "-g", "802-11-wireless.ssid", "con", "show", HOTSPOT) or HOTSPOT_SSID
    except CmdError:
        pass
    try:
        for line in run("nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device").splitlines():
            typ, state, conn = (_split_t(line) + ["", "", ""])[:3]
            if typ == "wifi" and state == "connected":
                st["mode"] = "hotspot" if conn == HOTSPOT else "client"
                st["ssid"] = conn
        for line in run("nmcli", "-t", "-f", "NAME,TYPE,AUTOCONNECT-PRIORITY", "con", "show").splitlines():
            name, typ, prio = (_split_t(line) + ["", "", "0"])[:3]
            if typ == "802-11-wireless" and name != HOTSPOT:
                st["saved"].append({"ssid": name, "priority": int(prio or 0),
                                    "active": name == st["ssid"]})
        st["ip"] = (run("hostname", "-I").split() or [None])[0]
    except CmdError as e:
        st["error"] = str(e)
    try:
        st["hotspot"]["password"] = run("nmcli", "-s", "-g", "802-11-wireless-security.psk",
                                        "con", "show", HOTSPOT, sudo=True) or None
    except CmdError:
        pass
    try:
        st["hotspot"]["auto"] = run("systemctl", "is-enabled", "wifi-fallback") == "enabled"
    except CmdError:
        pass
    return st


def wifi_scan() -> list[dict]:
    out = run("nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list",
              "--rescan", "yes", timeout=25)
    best: dict[str, dict] = {}
    for line in out.splitlines():
        ssid, signal, sec = (_split_t(line) + ["", "0", ""])[:3]
        if not ssid or ssid in (HOTSPOT_SSID, "DMX-BOX"):
            continue
        sig = int(signal or 0)
        if ssid not in best or sig > best[ssid]["signal"]:
            best[ssid] = {"ssid": ssid, "signal": sig, "secure": bool(sec and sec != "--")}
    return sorted(best.values(), key=lambda x: -x["signal"])


def wifi_add(ssid: str, password: str, priority: int = 10) -> None:
    if not ssid or len(ssid) > 32:
        raise CmdError("neplatné meno siete")
    if password and len(password) < 8:
        raise CmdError("heslo Wi-Fi má aspoň 8 znakov")
    try:
        run("nmcli", "con", "delete", ssid, sudo=True)
    except CmdError:
        pass
    sec = ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password] if password else []
    run("nmcli", "con", "add", "type", "wifi", "ifname", "wlan0", "con-name", ssid, "ssid", ssid,
        *sec, "connection.autoconnect", "yes", "connection.autoconnect-priority", str(priority),
        sudo=True)


def wifi_connect(ssid: str) -> None:
    """Prepne z hotspotu na sieť. Beží na pozadí – tablet sa medzitým odpojí."""
    def go():
        time.sleep(1.5)
        try:
            run("nmcli", "con", "down", HOTSPOT, sudo=True)
        except CmdError:
            pass
        try:
            run("nmcli", "con", "up", ssid, sudo=True, timeout=45)
            log.info("Wi-Fi: pripojené na %s", ssid)
        except CmdError as e:
            log.warning("Wi-Fi %s zlyhala (%s), späť na hotspot", ssid, e)
            try:
                run("nmcli", "con", "up", HOTSPOT, sudo=True, timeout=30)
            except CmdError:
                pass
    threading.Thread(target=go, daemon=True).start()


def wifi_delete(ssid: str) -> None:
    if ssid == HOTSPOT:
        raise CmdError("hotspot sa nedá zmazať")
    run("nmcli", "con", "delete", ssid, sudo=True)


def hotspot_set(on: bool) -> None:
    if on:
        later(1.5, "nmcli", "con", "up", HOTSPOT, sudo=True)
    else:
        later(1.5, "nmcli", "con", "down", HOTSPOT, sudo=True)


def hotspot_auto(on: bool) -> None:
    run("systemctl", "enable" if on else "disable", "--now", "wifi-fallback", sudo=True)


def hotspot_password(password: str) -> None:
    if len(password) < 8 or len(password) > 63:
        raise CmdError("heslo musí mať 8–63 znakov")
    run("nmcli", "con", "modify", HOTSPOT, "wifi-sec.psk", password, sudo=True)


# --- Bluetooth -------------------------------------------------------------------

def _bt_devices(kind: str) -> list[tuple[str, str]]:
    out = run("bluetoothctl", "devices", kind) if kind else run("bluetoothctl", "devices")
    res = []
    for line in out.splitlines():
        parts = line.split(" ", 2)
        if len(parts) >= 2 and parts[0] == "Device" and MAC_RE.match(parts[1]):
            res.append((parts[1], parts[2] if len(parts) > 2 else parts[1]))
    return res


def _bt_icon(mac: str) -> str:
    try:
        info = run("bluetoothctl", "info", mac, timeout=5)
    except CmdError:
        return ""
    m = re.search(r"Icon:\s*(\S+)", info)
    return m.group(1) if m else ""


def bt_status() -> dict:
    st = {"available": has("bluetoothctl"), "powered": False, "discoverable": False,
          "name": None, "devices": []}
    if not st["available"]:
        return st
    try:
        show = run("bluetoothctl", "show")
        st["powered"] = "Powered: yes" in show
        st["discoverable"] = "Discoverable: yes" in show
        m = re.search(r"Alias:\s*(.+)", show)
        st["name"] = m.group(1).strip() if m else None
        connected = {mac for mac, _ in _bt_devices("Connected")}
        for mac, name in _bt_devices("Paired"):
            icon = _bt_icon(mac)
            st["devices"].append({"mac": mac, "name": name, "connected": mac in connected,
                                  "speaker": icon.startswith("audio")})
    except CmdError as e:
        st["error"] = str(e)
    return st


def _mac(mac: str) -> str:
    if not MAC_RE.match(mac or ""):
        raise CmdError("neplatná MAC adresa")
    return mac


def bt_discoverable(on: bool) -> None:
    run("bluetoothctl", "discoverable", "on" if on else "off")
    if on:
        run("bluetoothctl", "pairable", "on")


def bt_forget(mac: str) -> None:
    run("bluetoothctl", "remove", _mac(mac))


def bt_disconnect(mac: str) -> None:
    run("bluetoothctl", "disconnect", _mac(mac))


def bt_scan(seconds: int = 12) -> list[dict]:
    paired = {mac for mac, _ in _bt_devices("Paired")}
    try:
        run("bluetoothctl", "--timeout", str(seconds), "scan", "on", timeout=seconds + 10)
    except CmdError:
        pass   # timeout scanu vracia niekedy nenulový kód
    return [{"mac": mac, "name": name} for mac, name in _bt_devices("")
            if mac not in paired and name.replace("-", ":") != mac]


def bt_connect(mac: str) -> None:
    """Spárovať a pripojiť zariadenie (BT reproduktor)."""
    _mac(mac)
    for step in (("pair", 30), ("trust", 10), ("connect", 30)):
        try:
            run("bluetoothctl", "--timeout", str(step[1]), step[0], mac, timeout=step[1] + 10)
        except CmdError as e:
            if step[0] == "pair" and "AlreadyExists" in str(e):
                continue
            if step[0] != "trust":
                raise


# --- zvuk -------------------------------------------------------------------------

def _sink_kind(name: str) -> str:
    n = name.lower()
    if n.startswith("bluez"):
        return "bluetooth"
    if "usb" in n:
        return "usb"
    if "hdmi" in n:
        return "hdmi"
    if "platform" in n or "bcm2835" in n or "mailbox" in n:
        return "jack"
    return "other"


KIND_NAMES = {"usb": "Zvuková karta USB (UCA202)", "jack": "Jack na Pi (3,5 mm)",
              "bluetooth": "Bluetooth reproduktor", "hdmi": "HDMI", "other": "Iný výstup"}


def audio_status() -> dict:
    st = {"available": has("pactl"), "default": None, "sinks": [], "volume": None}
    if not st["available"]:
        return st
    try:
        st["default"] = run("pactl", "get-default-sink")
        name = desc = None
        for line in run("pactl", "list", "sinks").splitlines():
            s = line.strip()
            if s.startswith("Name:"):
                name = s.split(":", 1)[1].strip()
            elif s.startswith("Description:") and name:
                desc = s.split(":", 1)[1].strip()
                kind = _sink_kind(name)
                if name == "auto_null":      # „Dummy Output“: PipeWire nenašiel žiadny skutočný výstup
                    name = None
                    continue
                if "null" in name.lower():
                    kind = "other"
                st["sinks"].append({"name": name, "description": desc, "kind": kind,
                                    "label": KIND_NAMES[kind] if kind != "other" else desc,
                                    "default": name == st["default"]})
                name = None
    except CmdError as e:
        st["error"] = str(e)
    try:
        v = run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@")
        m = re.search(r"([\d.]+)", v)
        st["volume"] = round(float(m.group(1)) * 100) if m else None
        st["muted"] = "MUTED" in v
    except CmdError:
        pass
    return st


def audio_output(sink: str) -> None:
    names = {s["name"] for s in audio_status()["sinks"]}
    if sink not in names:
        raise CmdError("výstup nenájdený")
    run("pactl", "set-default-sink", sink)
    # presunúť aj práve hrajúce streamy
    try:
        for line in run("pactl", "list", "short", "sink-inputs").splitlines():
            run("pactl", "move-sink-input", line.split("\t")[0], sink)
    except CmdError:
        pass


def audio_volume(percent: int) -> None:
    p = max(0, min(150, int(percent)))
    run("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0")
    run("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{p}%")


# --- Spotify Connect ---------------------------------------------------------------

def spotify_status() -> dict:
    st = {"installed": has("librespot"), "active": False}
    if st["installed"]:
        try:
            st["active"] = run("systemctl", "--user", "is-active", "librespot") == "active"
        except CmdError:
            pass
    return st


def spotify_set(on: bool) -> None:
    if on and not has("librespot"):
        raise CmdError("Spotify Connect nie je nainštalovaný (install.sh --spotify)")
    run("systemctl", "--user", "enable" if on else "disable", "--now", "librespot", timeout=30)


# --- systém -------------------------------------------------------------------------

def system_info() -> dict:
    info: dict = {"hostname": None, "version": None, "date": None, "throttled": None, "temp": None}
    try:
        info["hostname"] = run("hostname")
        info["version"] = run("git", "-C", str(ROOT), "rev-parse", "--short", "HEAD")
        info["date"] = run("git", "-C", str(ROOT), "log", "-1", "--format=%cs")
    except CmdError:
        pass
    try:
        info["throttled"] = run("vcgencmd", "get_throttled").split("=")[-1]
        info["temp"] = run("vcgencmd", "measure_temp").split("=")[-1]
    except CmdError:
        pass
    return info


def _in_service() -> bool:
    try:
        return run("systemctl", "--user", "is-active", "dmxbox") == "active"
    except CmdError:
        return False


def update() -> str:
    """git pull; ak beží ako služba, reštartuje sa."""
    out = run("git", "-C", str(ROOT), "pull", "--ff-only", timeout=60)
    if Path(ROOT / "scripts" / "dmxbox").exists():
        try:
            run("install", "-m", "755", str(ROOT / "scripts" / "dmxbox"), "/usr/local/bin/dmxbox",
                sudo=True)
        except CmdError:
            pass
    if _in_service():
        later(1.0, "systemctl", "--user", "restart", "dmxbox")
    return out.splitlines()[-1] if out else "hotovo"


def restart_app() -> None:
    if not _in_service():
        raise CmdError("aplikácia nebeží ako služba (spustená ručne)")
    later(1.0, "systemctl", "--user", "restart", "dmxbox")


def power(action: str) -> None:
    if action not in ("reboot", "poweroff"):
        raise CmdError("neznáma akcia")
    later(1.5, "systemctl", action, sudo=True)


def status() -> dict:
    return {"wifi": wifi_status(), "bt": bt_status(), "audio": audio_status(),
            "spotify": spotify_status(), "system": system_info()}
