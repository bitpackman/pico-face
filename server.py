#!/usr/bin/env python3
"""pico-face status server.

A cute ambient face for your AI-agent box. Serves the face UI (index.html)
and /status JSON aggregating, per your config.json:

  - service health (systemd / launchd / plain process checks)
  - Claude Code usage-window utilization (read-only, optional)
  - Claude Code session activity, inferred from process CPU only
  - a local task-queue directory (optional)
  - CPU temperature (Linux; omitted elsewhere)
  - affection ("tamagotchi") state, fed by petting and finished tasks

Stdlib only. Linux (incl. Raspberry Pi) and macOS.
Run:  python3 server.py   ->  http://localhost:8090/
"""
import json
import os
import platform
import subprocess
import time
import urllib.request
from datetime import date
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

BASE = Path(__file__).resolve().parent
HOME = Path.home()
IS_MAC = platform.system() == "Darwin"

DEFAULTS = {
    "name": "pico",             # character name shown in the UI
    "lang": "en",               # "en" or "ja"
    "port": 8090,
    "services": [],             # [{"name": ..., "type": "systemd-user|systemd|launchd|process", "target": ...}]
    "tasks_dir": None,          # dir with queue/ running/ done/ failed/ subdirs, or null
    "claude_usage": True,       # show Claude usage windows (unofficial endpoint)
    "claude_sessions": True,    # classify Claude Code sessions by CPU activity
    "session_pattern": "(^|/)claude( |$)",
    "credentials_path": "~/.claude/.credentials.json",
    "hot_temp_c": 78,
    "sweat_usage_pct": 85,
    "night_hours": [1, 7],      # sleeping face between these local hours
    "pets_per_day": 20,
    "pet_gain": 1.0,
    "greeting_bonus": 2.0,
    "task_gain": 5.0,
    "neglect_decay": 3.0,
}


def load_config():
    cfg = dict(DEFAULTS)
    p = BASE / "config.json"
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text()))
        except ValueError as e:
            print(f"config.json is invalid ({e}); using defaults")
    return cfg


CFG = load_config()
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
USAGE_CACHE_SEC = 300
_usage_cache = {"t": 0.0, "data": None}

# ---- affection ----------------------------------------------------------
PET_STATE = BASE / "pet_state.json"
LEVEL_THRESHOLDS = [0, 10, 25, 45, 70, 100, 140, 190]  # names live in the UI


def load_pet():
    try:
        return json.loads(PET_STATE.read_text())
    except (OSError, ValueError):
        # done_seen starts "now" so pre-existing done files give no burst
        return {"points": 0.0, "day": time.strftime("%Y-%m-%d"),
                "pets_today": 0, "last_pet_day": None, "done_seen": time.time()}


def save_pet(st):
    PET_STATE.write_text(json.dumps(st))


def level_of(points):
    lv = 1
    for i, th in enumerate(LEVEL_THRESHOLDS, 1):
        if points >= th:
            lv = i
    nxt = LEVEL_THRESHOLDS[lv] if lv < len(LEVEL_THRESHOLDS) else None
    return lv, nxt


def pet_rollover(st):
    """New day: reset daily pet counter, decay if it was ignored."""
    today = time.strftime("%Y-%m-%d")
    if st.get("day") == today:
        return
    try:
        gap = max(1, (date.today() - date.fromisoformat(st["day"])).days)
    except (ValueError, KeyError):
        gap = 1
    ignored = gap if st.get("last_pet_day") != st.get("day") else gap - 1
    if ignored > 0:
        st["points"] = max(0.0, st["points"] - CFG["neglect_decay"] * ignored)
    st["day"] = today
    st["pets_today"] = 0


def tasks_dir():
    return Path(os.path.expanduser(CFG["tasks_dir"])) if CFG["tasks_dir"] else None


def apply_task_gains(st):
    """+task_gain for each queued task finished since last check."""
    td = tasks_dir()
    if td is None or not (td / "done").is_dir():
        return
    seen = st.get("done_seen", time.time())
    newest, gained = seen, 0
    for p in (td / "done").iterdir():
        if p.is_file():
            m = p.stat().st_mtime
            if m > seen:
                gained += 1
            newest = max(newest, m)
    if gained:
        st["points"] = min(999.0, st["points"] + CFG["task_gain"] * gained)
    st["done_seen"] = newest


def recent_done(minutes=10):
    td = tasks_dir()
    if td is None or not (td / "done").is_dir():
        return False
    cutoff = time.time() - minutes * 60
    return any(p.stat().st_mtime > cutoff for p in (td / "done").iterdir() if p.is_file())


def affection_summary(st):
    lv, nxt = level_of(st["points"])
    return {"points": round(st["points"], 1), "level": lv,
            "next_at": nxt, "pets_today": st["pets_today"]}


# ---- daily whim ---------------------------------------------------------
WHIM_KEYS = ["harikiri", "mattari", "amaenbo", "ochame", "tereya"]


def whim_of_day():
    """Deterministic daily personality — same for every client all day."""
    d = date.today().toordinal()
    return {"key": WHIM_KEYS[(d * 7 + 3) % len(WHIM_KEYS)]}


# ---- presence (optional camera watcher POSTs here) ----------------------
OKAERI_GAP = 30 * 60
PRESENCE_FRESH = 10
_presence = {"present": False, "count": 0, "cx": 0.5, "ts": 0.0,
             "last_present": 0.0, "okaeri_until": 0.0}


def update_presence(data):
    now = time.time()
    present = bool(data.get("present"))
    if present:
        gap = now - _presence["last_present"]
        if _presence["last_present"] == 0 or gap > OKAERI_GAP:
            _presence["okaeri_until"] = now + 15
        _presence["last_present"] = now
    _presence.update(present=present, count=int(data.get("count") or 0),
                     cx=float(data.get("cx") or 0.5), ts=now)


def presence_summary():
    now = time.time()
    live = now - _presence["ts"] < PRESENCE_FRESH
    return {"watcher": live,
            "present": _presence["present"] if live else False,
            "count": _presence["count"] if live else 0,
            "cx": _presence["cx"],
            "okaeri": now < _presence["okaeri_until"]}


# ---- service health -----------------------------------------------------
def check_service(svc):
    kind, target = svc.get("type", "process"), svc["target"]
    try:
        if kind in ("systemd-user", "systemd"):
            args = ["systemctl"] + (["--user"] if kind == "systemd-user" else []) \
                 + ["is-active", target]
            r = subprocess.run(args, capture_output=True, text=True)
            return r.stdout.strip() or "unknown"
        if kind == "launchd":
            r = subprocess.run(["launchctl", "list", target],
                               capture_output=True, text=True)
            return "active" if r.returncode == 0 else "inactive"
        if kind == "process":
            r = subprocess.run(["pgrep", "-f", target], capture_output=True, text=True)
            return "active" if r.stdout.strip() else "inactive"
    except FileNotFoundError:
        pass
    return "unknown"


def service_states():
    return {svc["name"]: check_service(svc) for svc in CFG["services"]}


# ---- task queue ---------------------------------------------------------
def task_counts():
    td = tasks_dir()
    if td is None:
        return None
    counts = {}
    for name in ("queue", "running", "done", "failed"):
        d = td / name
        counts[name] = sum(1 for p in d.iterdir() if p.is_file()) if d.is_dir() else 0
    return counts


# ---- Claude usage windows (unofficial endpoint, read-only token) --------
def usage():
    if not CFG["claude_usage"]:
        return None
    now = time.time()
    if _usage_cache["data"] is not None and now - _usage_cache["t"] < USAGE_CACHE_SEC:
        return _usage_cache["data"]
    data = {"five_hour_pct": None, "seven_day_pct": None, "resets_at": None, "error": None}
    try:
        creds = Path(os.path.expanduser(CFG["credentials_path"]))
        token = json.loads(creds.read_text())["claudeAiOauth"]["accessToken"]
        req = urllib.request.Request(USAGE_URL, headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            j = json.load(resp)
        fh, sd = j.get("five_hour") or {}, j.get("seven_day") or {}
        # utilization is already a percentage
        data["five_hour_pct"] = round(fh.get("utilization") or 0)
        data["seven_day_pct"] = round(sd.get("utilization") or 0)
        data["resets_at"] = fh.get("resets_at")
    except Exception as e:  # expired token, offline, etc. — face shows "?"
        data["error"] = type(e).__name__
    _usage_cache.update(t=now, data=data)
    return data


# ---- Claude Code sessions, classified by CPU use only (no content) ------
_cpu_prev = {}      # pid -> (cpu_seconds, wall_time)
_last_active = {}   # pid -> last time we saw it burn CPU
WORKING_GRACE = 120   # active within 2 min  -> working
WAITING_WINDOW = 900  # quiet for 2-15 min   -> waiting for your reply


def _parse_ps_time(s):
    """'[[dd-]hh:]mm:ss[.ff]' -> seconds (Linux and macOS formats)."""
    days = 0
    if "-" in s:
        d, s = s.split("-", 1)
        days = int(d)
    sec = 0.0
    for part in s.split(":"):
        sec = sec * 60 + float(part)
    return days * 86400 + sec


def _cpu_seconds(pids):
    if not pids:
        return {}
    r = subprocess.run(["ps", "-o", "pid=,time=", "-p", ",".join(map(str, pids))],
                       capture_output=True, text=True)
    out = {}
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                out[int(parts[0])] = _parse_ps_time(parts[1])
            except ValueError:
                pass
    return out


def claude_session_detail():
    if not CFG["claude_sessions"]:
        return None
    now = time.time()
    r = subprocess.run(["pgrep", "-f", "--", CFG["session_pattern"]],
                       capture_output=True, text=True)
    pids = [int(x) for x in r.stdout.split() if x.isdigit()]
    cpu = _cpu_seconds(pids)
    working = waiting = idle = 0
    for pid in pids:
        sec = cpu.get(pid)
        prev = _cpu_prev.get(pid)
        if sec is not None:
            _cpu_prev[pid] = (sec, now)
            if prev is not None:
                dt = now - prev[1]
                dsec = sec - prev[0]
                if dt > 0 and dsec >= 0.05 and dsec / dt >= 0.02:
                    _last_active[pid] = now
        since = now - _last_active.get(pid, 0)
        if since < WORKING_GRACE:
            working += 1
        elif since < WAITING_WINDOW:
            waiting += 1
        else:
            idle += 1
    for dead in set(_cpu_prev) - set(pids):
        _cpu_prev.pop(dead, None)
        _last_active.pop(dead, None)
    return {"sessions": len(pids), "working": working,
            "waiting": waiting, "idle": idle}


# ---- CPU temperature ----------------------------------------------------
def cpu_temp():
    try:  # Linux only; macOS has no unprivileged equivalent
        raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
        return round(int(raw) / 1000, 1)
    except (OSError, ValueError):
        return None


# ---- status -------------------------------------------------------------
def build_status():
    svcs = service_states()
    tasks = task_counts()
    u = usage()
    cs = claude_session_detail()
    temp = cpu_temp()
    bad = [k for k, v in svcs.items() if v != "active"]
    hour = time.localtime().tm_hour

    pet = load_pet()
    pet_rollover(pet)
    apply_task_gains(pet)
    save_pet(pet)

    night_start, night_end = CFG["night_hours"]
    running = (tasks or {}).get("running", 0)
    # mood: the one-glance summary the face renders (priority order)
    if bad:
        mood = "trouble"
    elif temp is not None and temp >= CFG["hot_temp_c"]:
        mood = "hot"
    elif u and u["five_hour_pct"] is not None and u["five_hour_pct"] >= CFG["sweat_usage_pct"]:
        mood = "sweat"
    elif recent_done():
        mood = "proud"
    elif running > 0 or (cs and cs["working"] > 0):
        mood = "working"
    elif cs and cs["waiting"] > 0:
        mood = "waiting"
    elif night_start <= hour < night_end:
        mood = "sleeping"
    else:
        mood = "idle"

    return {
        "time": time.strftime("%H:%M:%S"),
        "mood": mood,
        "ui": {"name": CFG["name"], "lang": CFG["lang"]},
        "services": svcs,
        "bad_services": bad,
        "tasks": tasks,
        "usage": u,
        "claude": cs,
        "cpu_temp": temp,
        "affection": affection_summary(pet),
        "whim": whim_of_day(),
        "presence": presence_summary(),
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(BASE), **kw)

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/status":
            self._json(build_status())
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/presence":
            # local watcher only — never accept presence data off-box
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                self.send_error(403)
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
                update_presence(json.loads(self.rfile.read(n)))
            except (ValueError, OSError):
                self.send_error(400)
                return
            self.send_response(204)
            self.end_headers()
            return
        if self.path != "/pet":
            self.send_error(404)
            return
        st = load_pet()
        pet_rollover(st)
        gain = 0.0
        if st["pets_today"] < CFG["pets_per_day"]:
            gain = CFG["pet_gain"]
            if st.get("last_pet_day") != st["day"]:
                gain += CFG["greeting_bonus"]
            st["points"] = min(999.0, st["points"] + gain)
        st["pets_today"] += 1
        st["last_pet_day"] = st["day"]
        save_pet(st)
        out = affection_summary(st)
        out["gain"] = gain
        self._json(out)

    def log_message(self, fmt, *args):  # keep logs quiet
        pass


if __name__ == "__main__":
    os.chdir(BASE)
    print(f"pico-face on http://0.0.0.0:{CFG['port']}/")
    HTTPServer(("0.0.0.0", CFG["port"]), Handler).serve_forever()
