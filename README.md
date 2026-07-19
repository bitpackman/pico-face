# pico-face

**A cute ambient face for your AI-agent box.** 🥺

pico-face turns a Raspberry Pi (or Mac) that runs background AI agents into a
little creature with feelings. It watches your services, your Claude Code
sessions, and your usage limits — and tells you how things are going with its
face, not with a dashboard.

[日本語 README](README.ja.md)

- **Glowing eyes, 9 moods** — idle 😪 / working ✨ / waiting-for-your-reply ❗ /
  proud 😤 / overheating 🥵 / usage-limit sweat 💦 / trouble ＞＜ / sleeping 😴 /
  heart eyes 💗 when you pet it
- **Tamagotchi affection** — pet it daily, finish tasks together, level the
  bond from "stranger" to "forever". Ignore it and the bond decays.
- **A daily whim** — every day it wakes up energetic, laid-back, clingy,
  silly, or shy. Gestures, tempo and lines change accordingly.
- **Claude Code awareness** — sees how many sessions are *working* vs
  *waiting for your reply* (via process CPU only — it never reads content).
- **PWA** — add it to your phone's home screen; eyes follow your finger.
- **Zero dependencies** — Python stdlib only. One HTML file. No build step.

## Quick start

```bash
git clone https://github.com/bitpackman/pico-face.git
cd pico-face
cp config.example.json config.json   # edit to taste
python3 server.py                    # -> http://localhost:8090/
```

Preview every mood with `?mood=idle|working|waiting|proud|hot|sweat|trouble|sleeping|heart`.

## Run it permanently

**Raspberry Pi / Linux (systemd user service)**

```bash
cp deploy/pico-face.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pico-face.service
loginctl enable-linger $USER
```

**macOS (launchd)**

```bash
sed "s|__HOME__|$HOME|g" deploy/com.picoface.server.plist > ~/Library/LaunchAgents/com.picoface.server.plist
launchctl load ~/Library/LaunchAgents/com.picoface.server.plist
```

## Configuration (`config.json`)

| key | default | description |
|---|---|---|
| `name` | `"pico"` | your creature's name |
| `lang` | `"en"` | UI language: `"en"` or `"ja"` |
| `port` | `8090` | HTTP port |
| `services` | `[]` | services to watch; a dead one triggers the crying face |
| `tasks_dir` | `null` | dir with `queue/ running/ done/ failed/` subdirs (finished tasks feed affection) |
| `claude_usage` | `true` | show Claude usage windows (see note below) |
| `claude_sessions` | `true` | classify Claude Code sessions by CPU activity |
| `session_pattern` | `"--sdk-url"` | pgrep pattern that identifies session processes |
| `hot_temp_c` | `78` | CPU temp for the overheating face (Linux only) |
| `sweat_usage_pct` | `85` | 5-hour window % for the nervous face |
| `night_hours` | `[1, 7]` | sleeping face between these local hours |
| `pets_per_day` … `neglect_decay` | | affection tuning knobs |

Service entry types:

```jsonc
{ "name": "my-agent",  "type": "systemd-user", "target": "my-agent.service" }   // systemctl --user
{ "name": "postgres",  "type": "systemd",      "target": "postgresql.service" } // systemctl
{ "name": "my-daemon", "type": "launchd",      "target": "com.example.daemon" } // macOS
{ "name": "ollama",    "type": "process",      "target": "ollama serve" }       // pgrep -f
```

## Phone / PWA

The server listens on `0.0.0.0`, so any device on your LAN or VPN
(e.g. Tailscale) can open it. For the full PWA experience (home-screen
install, service worker) you need HTTPS; with Tailscale that's one command:

```bash
tailscale serve --bg --https=8444 8090
# -> https://<your-machine>.<tailnet>.ts.net:8444/
```

Then "Add to Home Screen" on your phone.

## Privacy & security notes

- **Claude session detection reads no content.** It only samples per-process
  CPU time (`ps`) to tell "working" from "waiting". Session counts, nothing else.
- **Usage windows** are fetched from an **unofficial** Anthropic endpoint
  (the same one the `/usage` command uses), by reading the OAuth token from
  `~/.claude/.credentials.json` **read-only**. It never writes or refreshes
  the token. Unofficial means it may break someday; set `"claude_usage": false`
  to turn it off.
- The affection state lives in `pet_state.json` next to the server. Nothing
  leaves your machine.
- If you expose the port beyond localhost, anyone who can reach it can see
  your service names and pet your creature (max-affection griefing is the
  worst case — the `/pet` endpoint is rate-limited per day). Keep it inside
  your LAN/VPN.

## Optional: camera presence (Raspberry Pi + Sony IMX500)

If you have a [Raspberry Pi AI Camera](https://www.raspberrypi.com/products/ai-camera/)
(Sony IMX500), `watcher.py` runs person detection **on the camera sensor's own
NPU** and the face's eyes will follow you around the room; after 30+ minutes
away you get a "welcome back!". No frames are ever stored or transmitted —
only `{present, count, cx}` numbers are POSTed to localhost.

```bash
python3 watcher.py   # requires picamera2 + IMX500 models (bundled with Raspberry Pi OS)
```

Without a camera you still get the phone equivalents: welcome-back on opening
the app after 3+ hours, and eyes that chase your finger.

## Make it yours

- Character name and language: `config.json`
- Lines it says (and both language packs): `I18N` in `index.html`
- Faces: each mood is a small CSS block in `index.html` — tweak away
- Icon: `python3 make_icons.py`
- Affection levels/curve: `LEVEL_THRESHOLDS` in `server.py`

## License

MIT
