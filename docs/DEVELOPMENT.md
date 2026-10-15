# Development

> **Português:** esta página em português: [DEVELOPMENT.pt-BR.md](DEVELOPMENT.pt-BR.md).

```
Twitch chat (anonymous IRC) ──► team sorter (!joinsort) ──► voice controller (who speaks)
                                                                 │ messages from the active chatter
                                                                 ▼
OBS browser source ◄── WebSocket + /audio/<id>.wav ◄── TTS engine (dummy | sapi | omnivoice | custom)
(goblin png ⇄ gif + tint)

Desktop app (Tauri) ── starts ──► Python backend (sidecar exe) ── serves ──► /panel  /overlay  /api
```

## Setup and run (PowerShell)

All commands are PowerShell, run from the repository root. Requires Python 3.13, Rust and Node.

**First-time setup**

```powershell
py -3.13 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
cd app; npm install; cd ..
.\tts_server\setup.ps1          # voice server: PyTorch CUDA + OmniVoice (several GB)
```

**Start the backend from source** (latest Python code; also starts the TTS server)

```powershell
.venv\Scripts\python -m goblin_yapper --data-dir "$env:APPDATA\com.goblinyapper.desktop"
```

Leave it running. The app detects it on port 8765 and uses it instead of its bundled backend.
Without the app, open the panel in a browser: `http://127.0.0.1:8765/panel`.
Close the app before restarting the backend: whichever server holds port 8765 is the one in use.

**Open the app**

```powershell
& ".\app\src-tauri\target\debug\goblin-yapper.exe"     # latest debug build
& ".\app\src-tauri\target\release\goblin-yapper.exe"   # release build (made by build.ps1)
```

**Rebuild the app without making an installer**

```powershell
cd app; npx tauri build --debug --no-bundle; cd ..   # -> app\src-tauri\target\debug\goblin-yapper.exe
cd app; npx tauri dev; cd ..                          # or: compile and launch in one step
```

Needed after changing the icon, the loading screen (`app/src/index.html`) or `main.rs`.
Panel and overlay changes only need the backend restarted.

**Build the installer (.msi)**

```powershell
.\build.ps1
# -> app\src-tauri\target\release\bundle\msi\Goblin Yapper_<version>_x64_pt-BR.msi
```

`build.ps1` runs the tests, freezes the backend with PyInstaller into
`app/src-tauri/binaries/goblin-yapper-server-<target>.exe`, then `tauri build` bundles the app, the backend and
the WebView2 bootstrapper into an `.msi`. The installer only ships the TTS server's code; the app installs the
voice runtime on first use (Voz tab) with [uv](https://github.com/astral-sh/uv) (pinned, checksum verified), a
standalone Python 3.13, PyTorch with CUDA 12.8 and OmniVoice.

**Run the tests**

```powershell
.venv\Scripts\python -m pytest
```

**Logs**

```powershell
Get-Content "$env:APPDATA\com.goblinyapper.desktop\goblin-yapper.log" -Tail 30   # backend
Get-Content "$env:APPDATA\com.goblinyapper.desktop\tts\tts-server.log" -Tail 30  # TTS server
```

## Operator commands and HTTP API

The panel buttons, the console (`help` when the backend runs in a terminal) and the HTTP API all use these same
commands. `<time>` (team) is `azul`, `verde`, `roxo` or `amarelo`.

| command | what it does |
|---------|--------------|
| `open` / `close` | Open or close the queue for `!joinsort` |
| `teams <1-4>` | Number of teams. Lowering it moves members of removed teams into the others |
| `sort` | Sort everyone in the queue into balanced teams |
| `resort` | Put everyone back in the queue and sort again |
| `reset` | Put everyone from the teams back in the queue |
| `clear` | Empty the queue and all teams |
| `add <user>` | Add someone by hand (works even with the queue closed) |
| `move <user> <time\|fila>` | Move someone to another team, or back to the queue (`fila`) |
| `remove <user>` | Take someone out completely |
| `voice <time>` | Give the voice to a random person on that team |
| `voice any` | Give the voice to a random person on any team |
| `voice` / `next [time]` | Another person from that team (default: the last speaker's team) |
| `give <user>` | Give the voice to a specific person (they don't need to be on a team) |
| `stop [time\|user]` | Take the voice away and cut their audio (no argument: everyone) |
| `multivoice <on\|off>` | One speaker per team at the same time; lines still play one at a time |
| `skip` | Drop the line in progress (stuck in generation or playing); the speech queue goes on |
| `autoremove <on\|off> [min]` | Remove from the queue and teams whoever writes nothing in chat for `min` minutes (only counts while the chat is connected) |
| `autorotate <on\|off> [min]` | Pass the voice to another chatter of the same team every `min` minutes, once the current line ends |
| `hideidle <on\|off>` | Each team's source hides its goblin while nobody on the team has the voice |
| `channel <canal\|off>` | Connect to a channel's chat (name or pasted link), or disconnect |
| `tint <time> <#rrggbb\|off> [0-1]` | Team goblin tint color and strength |
| `teamvoice <time\|default> <perfil\|none>` | Voice profile a team speaks with (Voz tab) |
| `engine <server\|sapi\|dummy>` | Switch the TTS engine |
| `test <time> <texto>` | Make that team's goblin say a test line |
| `testvoice <time>` | The team's goblin says the fixed phrase (`[tts] test_phrase`) in the team's voice (**Testar voz** button) |
| `language <en\|pt-BR>` | The panel's language (saved in `settings.json`, as `ui.language`) |
| `state` | Print queue, teams and who has the voice |

```
POST /api/command   {"command": "sort"}
GET  /api/state
WS   /ws            (state / speak / idle / stop / assets / notice pushes)
```

**Messages in two languages.** The server never sends sentences: it sends a key and values, and the panel
translates them into the chosen language. The reply to `POST /api/command` is
`{"ok": true, "key": "msg.sorted", "params": {"count": 3}, "output": "3 sorted", "state": {...}}`: `output` is
the same text in English (for `curl` and the console). The app's HTTP errors and the notices
(`{"type": "notice", ...}`) use the same shape (`key`, `params`, `text`). `state.language` is the chosen language
(`null` until the operator picks one).

**Who plays each line.** On connecting to `/ws`, each overlay sends
`{"type": "hello", "role": "overlay", "team": "azul" | null, "audio": true}` (the panel sends `role: "panel"`;
the panel's thumbnails use `?preview=1` and don't count). Every client gets the `speak` for each line, but only
one gets `play: true` (`App.pick_player`): the overlay pinned to the line's team, else the main overlay, else
an open panel. That client plays `url` and answers `{"type": "ended", "id": n}`. `state.overlays` lists the
connected OBS sources.

## Configuration

The data folder's `config.toml` is created from `goblin_yapper/default_config.toml` on first run. It holds the
chat commands (`[twitch]`), TTS limits (`max_queue`, `skip_commands`), default tint colors
(`[teams.tint.<team>]`) and the engines. Changes made in the panel (the language included, `ui.language`) go to `settings.json`, so `config.toml` and
its comments stay untouched.

## TTS server and engines

The voice runs in a separate **TTS server** (`tts_server/`): its own Python environment with PyTorch (CUDA) and
OmniVoice, which loads the model on the GPU once. The backend starts it automatically and stops it on exit
(`[tts.server] autostart`). If one is already running at `[tts.server] url`, it is used instead.

```
backend (goblin_yapper) ──HTTP──► TTS server (tts_server/server.py) ──► engine (engines/omnivoice_engine.py)
     /api/tts/* proxy                profiles, pipeline, params              OmniVoice on the GPU
```

Profiles live in `tts\profiles\<id>\` (`reference.wav`, `profile.json`, `omnivoice.pt`). The `.wav` and
transcript are the source, so another engine can rebuild its own cache from them.

**Changing the TTS engine**: add `tts_server/engines/<name>_engine.py` with an `Engine` subclass (`params()`,
`transcribe()`, `build_profile()`, `synthesize()`; see `engines/base.py`), register it in
`engines/__init__.py`, and set `[tts.server] engine = "<name>"`. The Voz tab builds its form from the engine's
`params()`, so nothing in the app needs to change.

Other engines (`[tts] engine` in `config.toml`, or the switch in the Voz tab):

| engine   | what it is                                                     |
|----------|----------------------------------------------------------------|
| `server` | the TTS server above (default)                                 |
| `sapi`   | Windows voices (`[tts.sapi] voice = "Microsoft Maria Desktop"` for pt-BR) |
| `dummy`  | babble tones, for testing without a GPU                         |
| `custom` | your own Python function, see `scripts/my_tts.py`               |

## Interface languages

The text of the panel and the overlay lives in `goblin_yapper/web/i18n/en.json` (the reference language) and
`pt-BR.json`; `web/i18n.js` loads it. In HTML use `data-i18n="key"` (and `data-i18n-title`,
`data-i18n-placeholder`); in JavaScript, `t("key", {value: ...})`. The server's messages use the same keys
(`msg.*`, `err.*`, `notice.*`, `http.*`, `tts.*`) through `goblin_yapper/i18n.py`.

To add a text: add the key to **both** files. `tests/test_i18n.py` fails if the files have different keys, if a
page uses a key that does not exist, or if the server sends a key with no text. For a third language: a new
`<language>.json`, its code in `LANGUAGES` (`goblin_yapper/i18n.py` and `web/i18n.js`) and an option in the
panel's selector. Logs and the console stay in English. The shared vocabulary is in
[GLOSSARY.md](../GLOSSARY.md). Documents come in pairs (`X.md` in English and `X.pt-BR.md`).
