"""The link to your iPhone (ios/; previously the Android app): it finds this Mac on the Wi-Fi, pairs once with a code, then copies the
phone bundle (bundle.py) whenever it opens.

- Finding: Bonjour, service type _nbastats._tcp (the phone browses for it).
- A small separate server listens on the local network on SHARE_PORT; the main app stays on 127.0.0.1.
  Apart from pairing, every request must carry a paired phone's token.
- Pairing: the phone asks; this Mac shows a 6-digit code on its Phone page; the phone sends it back and
  gets a random token. Adapted from Spotify Stats' nearby sharing, phones only.
- The bundle is rebuilt only when the data or the unavailable list has changed since the last one.
"""

import gzip
import hmac
import json
import secrets
import shutil
import socket
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse

from . import bundle, config, model, tracker

SERVICE = "_nbastats._tcp.local."
SHARE_PORT = 8014           # fixed, so the phone finds it again after a restart (Spotify Stats uses 8013)
CODE_SECONDS = 300
MAX_CODE_ATTEMPTS = 5
MAX_PENDING = 3

_incoming: dict[str, dict] = {}   # pairing requests waiting for their code: phone id -> name, code, expiry
_lock = threading.Lock()
_bundle_lock = threading.Lock()
_zc = None
_server = None
_port: int | None = None
_ip: str | None = None
last_copy: dict = {}              # phone id -> when it last copied (shown on the Phone page)


class PhoneError(Exception):
    pass


def _file(name: str) -> Path:
    return config.DATA_DIR / name


def _read(name: str, default):
    try:
        return json.loads(_file(name).read_text())
    except (FileNotFoundError, ValueError):
        return default


def _write(name: str, value) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _file(name).with_suffix(".tmp")
    tmp.write_text(json.dumps(value))
    tmp.replace(_file(name))


def device_id() -> str:
    d = _read("device.json", {})
    if not d.get("id"):
        d = {"id": secrets.token_hex(8)}
        _write("device.json", d)
    return d["id"]


def phones() -> dict[str, dict]:
    return _read("phones.json", {})


def check_token(phone_id: str | None, authorization: str | None) -> bool:
    token = phones().get(phone_id or "", {}).get("token")
    given = (authorization or "").removeprefix("Bearer ").strip()
    return bool(token) and hmac.compare_digest(token, given)


def incoming_request(info: dict) -> None:
    phone = str(info.get("id") or "")[:32]
    if not phone:
        raise PhoneError("Missing device id.")
    with _lock:
        for key in [k for k, v in _incoming.items() if v["expires"] < time.time()]:
            _incoming.pop(key)
        if phone not in _incoming and len(_incoming) >= MAX_PENDING:
            raise PhoneError("Too many pairing requests. Try again in a few minutes.")
        _incoming[phone] = {"id": phone, "name": str(info.get("name") or "A phone")[:60],
                            "code": f"{secrets.randbelow(10 ** 6):06d}", "expires": time.time() + CODE_SECONDS, "attempts": 0}


def incoming_confirm(phone: str, code: str) -> dict:
    with _lock:
        req = _incoming.get(phone)
        if not req or req["expires"] < time.time():
            raise PhoneError("No pairing request is waiting. Start again on the phone.")
        req["attempts"] += 1
        if req["attempts"] > MAX_CODE_ATTEMPTS:
            _incoming.pop(phone)
            raise PhoneError("Too many wrong codes. Start again on the phone.")
        if not hmac.compare_digest(req["code"], str(code).strip()):
            raise PhoneError("That code isn't right. Check the code on your Mac's Phone page.")
        _incoming.pop(phone)
    token = secrets.token_urlsafe(32)
    all_phones = phones()
    all_phones[phone] = {"name": req["name"], "token": token, "paired_at": time.time()}
    _write("phones.json", all_phones)
    return {"id": device_id(), "name": socket.gethostname().removesuffix(".local"), "token": token}


def pending() -> list[dict]:
    with _lock:
        return [{"id": r["id"], "name": r["name"], "code": r["code"]} for r in _incoming.values() if r["expires"] > time.time()]


def unpair(phone: str) -> None:
    all_phones = phones()
    all_phones.pop(phone, None)
    _write("phones.json", all_phones)


# --- The bundle ---------------------------------------------------------------------

def _signature() -> list:
    """Changes whenever the bundle would: any cache file, the unavailable lists, the injury report or the saved predictions."""
    files = list(config.CACHE_DIR.glob("*.json")) if config.CACHE_DIR.exists() else []
    unavailable = config.UNAVAILABLE_FILE.stat().st_mtime if config.UNAVAILABLE_FILE.exists() else 0
    watched = [_file("predictions.json"), _file("game_outs.json"), _file("injuries.json")]
    changed = [f.stat().st_mtime if f.exists() else 0 for f in watched]
    return [len(files), max((f.stat().st_mtime for f in files), default=0), unavailable, *changed, bundle.FORMAT]


def bundle_file() -> Path:
    """The current gzipped bundle, rebuilt first if the data has changed since it was made."""
    packed, sig_file = _file("phone-bundle.db.gz"), "phone-bundle.json"
    with _bundle_lock:
        sig = _signature()
        if not packed.exists() or _read(sig_file, {}).get("signature") != sig:
            raw = _file("phone-bundle.db")
            meta = bundle.build(raw)
            tmp = packed.with_suffix(".tmp")
            with open(raw, "rb") as src, gzip.open(tmp, "wb", compresslevel=6) as out:
                shutil.copyfileobj(src, out)
            tmp.replace(packed)
            raw.unlink(missing_ok=True)
            _write(sig_file, {"signature": sig, "version": meta["version"], "built_at": time.time()})
    return packed


def bundle_info() -> dict:
    return _read("phone-bundle.json", {})


# --- The Wi-Fi server ------------------------------------------------------------------

share_app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@share_app.post("/share/pair/request")
def pair_request(info: dict = Body(...)):
    try:
        incoming_request(info)
    except PhoneError as e:
        raise HTTPException(429, str(e))
    return {"ok": True}


@share_app.post("/share/pair/confirm")
def pair_confirm(body: dict = Body(...)):
    try:
        return incoming_confirm(str(body.get("id") or ""), str(body.get("code") or ""))
    except PhoneError as e:
        raise HTTPException(403, str(e))


@share_app.get("/share/bundle/version")
def bundle_version(x_device_id: str | None = Header(None), authorization: str | None = Header(None)):
    """Lets the phone skip the download when it already has this data."""
    if not check_token(x_device_id, authorization):
        raise HTTPException(401, "Not paired with this Mac")
    return {"signature": _signature(), "built": bundle_info().get("signature") == _signature(), "version": bundle_info().get("version")}


@share_app.get("/share/bundle")
def get_bundle(x_device_id: str | None = Header(None), authorization: str | None = Header(None)):
    if not check_token(x_device_id, authorization):
        raise HTTPException(401, "Not paired with this Mac")
    path = bundle_file()
    last_copy[x_device_id] = time.time()
    return FileResponse(path, media_type="application/gzip", filename="nba-bundle.db.gz",
                        headers={"X-Bundle-Version": str(bundle_info().get("version", 0))})


@share_app.post("/share/picks")
def post_picks(body: dict = Body(...), x_device_id: str | None = Header(None), authorization: str | None = Header(None)):
    """Picks the phone saved while this Mac was asleep (tracker.merge_phone)."""
    if not check_token(x_device_id, authorization):
        raise HTTPException(401, "Not paired with this Mac")
    picks = body.get("picks")
    if not isinstance(picks, list):
        raise HTTPException(400, "Expected a list of picks")
    return {"taken": tracker.merge_phone(picks[:2000])}


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _announce() -> None:
    global _zc, _ip
    from zeroconf import IPVersion, ServiceInfo, Zeroconf
    _ip = _local_ip()
    zc = Zeroconf(ip_version=IPVersion.V4Only)
    zc.register_service(ServiceInfo(
        SERVICE, f"NBAStats-{device_id()}.{SERVICE}", addresses=[socket.inet_aton(_ip)], port=_port,
        properties={"id": device_id(), "name": socket.gethostname().removesuffix(".local")},
        server=f"nbastats-{device_id()}.local."))
    _zc = zc


def _stop_announcing() -> None:
    global _zc
    zc, _zc = _zc, None
    if zc:
        try:
            zc.unregister_all_services()
        finally:
            zc.close()


def _watch_address() -> None:
    """macOS changes the Wi-Fi address now and then; Bonjour is tied to the one it started on."""
    while _server:
        time.sleep(30)
        try:
            if _local_ip() != _ip:
                _stop_announcing()
                _announce()
        except Exception:
            pass


def start() -> None:
    global _server, _port
    if _server:
        return
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", SHARE_PORT))
    except OSError:  # taken (e.g. ./run.sh and the app both running): any free port; Bonjour says which
        sock.bind(("0.0.0.0", 0))
    sock.listen(16)
    _port = sock.getsockname()[1]
    _server = uvicorn.Server(uvicorn.Config(share_app, loop="asyncio", http="h11", lifespan="off", log_config=None))
    threading.Thread(target=lambda: _server.run(sockets=[sock]), daemon=True, name="phone-server").start()
    try:
        _announce()
    except Exception:  # no network yet: the watcher announces once there is one
        pass
    threading.Thread(target=_watch_address, daemon=True, name="phone-bonjour").start()


def status() -> dict:
    return {"running": _server is not None, "port": _port, "ip": _ip, "pending": pending(),
            "phones": [{"id": k, **{x: v.get(x) for x in ("name", "paired_at")}, "last_copy": last_copy.get(k)}
                       for k, v in phones().items()],
            "bundle": bundle_info()}
