# Goblin Yapper

Twitch team sorter + TTS "goblin" overlay for OBS. Spec: [Predicates.md](Predicates.md).

```
Twitch chat (anonymous IRC) ──► team sorter (!joinsort) ──► voice controller (who speaks)
                                                                 │ messages from the active chatter
                                                                 ▼
OBS browser source ◄── WebSocket + /audio/<id>.wav ◄── TTS engine (dummy | sapi | omnivoice | custom)
(goblin png ⇄ gif + tint)

Desktop app (Tauri) ── starts ──► Python backend (sidecar exe) ── serves ──► /panel  /overlay  /api
```

## Setup and run (PowerShell)

All commands are PowerShell, run from the project folder
(the repository root).

**First-time setup**

```powershell
py -3.13 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
cd app; npm install; cd ..
```

**Start the backend from source** (latest Python code; required for GPU TTS)

```powershell
.venv\Scripts\python -m goblin_yapper --data-dir "$env:APPDATA\com.goblinyapper.desktop"
```

Leave it running. The app detects it on port 8765 and uses it instead of its bundled backend.
Without the app, open the panel in a browser: `http://127.0.0.1:8765/panel`.

**Open the app**

```powershell
# latest compiled build (debug)
& ".\app\src-tauri\target\debug\goblin-yapper.exe"

# release build (made by build.ps1)
& ".\app\src-tauri\target\release\goblin-yapper.exe"
```

Close the app before restarting the backend: whichever server holds port 8765 is the one in use.

**Rebuild the app without making an installer**

```powershell
cd app; npx tauri build --debug --no-bundle; cd ..   # -> app\src-tauri\target\debug\goblin-yapper.exe
cd app; npx tauri dev; cd ..                          # or: compile and launch in one step
```

Needed after changing the icon, the loading screen (`app/src/index.html`) or `main.rs`.
Panel and overlay changes only need the backend restarted from source.

**Build the installer (.msi)**

```powershell
.\build.ps1
# -> app\src-tauri\target\release\bundle\msi\Goblin Yapper_0.1.0_x64_pt-BR.msi
```

**Run the tests**

```powershell
.venv\Scripts\python -m pytest
```

**Logs and data**

```powershell
Get-Content "$env:APPDATA\com.goblinyapper.desktop\goblin-yapper.log" -Tail 30   # backend log
explorer "$env:APPDATA\com.goblinyapper.desktop"                                 # config, settings, assets
```

## Desktop app (Windows installer)

`build.ps1` runs the tests, freezes the backend with PyInstaller into
`app/src-tauri/binaries/goblin-yapper-server-<target>.exe`, then `tauri build` bundles the app,
the backend and the WebView2 bootstrapper into an `.msi`. Requires Python 3.13, Rust and Node.

Installed app:
- the window is the operator panel (`/panel`): drag chatters between teams, voice buttons, tint pickers,
  goblin image upload, OBS overlay URLs to copy.
- user data lives in `%APPDATA%\com.goblinyapper.desktop\` — `config.toml`, `settings.json` (panel changes),
  `assets\`, `voices\`, `scripts\`, `goblin-yapper.log`.
- the bundled backend has no PyTorch, so `omnivoice`/GPU `custom` engines fall back to the Windows voice.
  For GPU TTS, start the backend from source (see Setup and run) **before** opening the app: it detects the server on
  port 8765 and attaches to it instead of starting its own.

## Twitch chat commands

What viewers type in chat:

| command | what it does |
|---------|--------------|
| `!joinsort` or `!joinsorting` | Join the queue. Only works while the queue is **open**. After a sort, late joiners go straight into the smallest team (`auto_assign_late`). |
| `!leavesort` | Leave the queue or their team. |

The chatter who **has the voice** doesn't type a command: their normal chat messages are read by the TTS
and their team's goblin talks. Before reading:

- messages starting with `!` are skipped (`skip_commands`)
- links and Twitch emotes are removed
- at most 5 messages wait in line; extra ones are dropped (`max_queue`)

The command names and limits are set in `config.toml` (`[twitch]` and `[tts]`).

## Operator commands

What you use to run the game: the panel buttons, the console (`help` when the backend runs from source in
a terminal) and the HTTP API all use these same commands. `<time>` is `azul`, `verde`, `roxo` or `amarelo`.

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
| `voice` / `next` | Another person from the same team as the current speaker |
| `give <user>` | Give the voice to a specific person (they don't need to be on a team) |
| `stop` | Take the voice away and cut the audio |
| `channel <canal\|off>` | Connect to a channel's chat (name or pasted link), or disconnect |
| `tint <time> <#rrggbb\|off> [0-1]` | Team goblin tint color and strength |
| `test <time> <texto>` | Make that team's goblin say a test line |
| `state` | Print queue, teams and who has the voice |

The panel runs at `http://127.0.0.1:8765/panel` (also works in a browser or as an OBS custom dock).
HTTP API:

```
POST /api/command   {"command": "sort"}
GET  /api/state
WS   /ws            (state / speak / idle / stop / assets pushes)
```

## OBS

Add a **Browser Source** at `http://127.0.0.1:8765/overlay` (transparent background).
Enable "Control audio via OBS" if you want the TTS on its own mixer channel.

- `?team=azul&audio=0` to pin one goblin per team (one source per team); keep **one** source with audio on.
- `?size=400`, `?label=0`.

Goblin images go in `assets/`: `goblin.png` (idle) + `goblin.gif` (talking). Each team gets the same
goblin tinted with its own color, set per team in `config.toml` (`[teams.tint.azul] color / strength`)
or live with `tint azul #1e40ff 0.7` / `tint azul off`. A neutral/grayish goblin tints best.
Per-team images (`azul.png` / `azul.gif`) override the shared ones if present.
Without images the built-in goburin goblin (drawn as SVG, tinted per team) is used.

## TTS

`[tts] engine` in `config.toml`:

| engine      | needs                                  |
|-------------|----------------------------------------|
| `dummy`     | nothing (babble tones, for testing)    |
| `sapi`      | Windows (`voice = "Microsoft Maria Desktop"` for pt-BR) |
| `omnivoice` | `torch` (CUDA build) + `omnivoice` package |
| `custom`    | your script, see `scripts/my_tts.py`   |

Per-team cloned voices: `[tts.voices.<team>]` with `ref_audio` / `ref_text`; passed to the engine as `voice`.
