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
.\tts_server\setup.ps1          # voice server: PyTorch CUDA + OmniVoice (several GB)
```

**Start the backend from source** (latest Python code; also starts the TTS server)

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
  `assets\`, `tts\` (voice profiles, TTS server log), `goblin-yapper.log`.
- **voice, first run**: the installer is small and only ships the TTS server's code. On the **Voz** tab,
  click **Instalar servidor de voz**: it downloads [uv](https://github.com/astral-sh/uv) (pinned, checksum
  verified), a standalone Python 3.13, PyTorch with CUDA 12.8 and OmniVoice (~3.5 GB download, ~8 GB on disk) into
  `%LOCALAPPDATA%\GoblinYapper\voice-runtime\`, then starts the server. The voice model (~3 GB) downloads to
  the Hugging Face cache the first time the server starts. No system Python is needed.
- uninstalling the app keeps the voice runtime and your data; delete `%LOCALAPPDATA%\GoblinYapper\` and
  `%APPDATA%\com.goblinyapper.desktop\` to remove them.
- a backend run from source still works alongside: start it **before** opening the app and the app attaches to
  it on port 8765 instead of starting its own.

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
| `voice` / `next [time]` | Another person from that team (default: the last speaker's team) |
| `give <user>` | Give the voice to a specific person (they don't need to be on a team) |
| `stop [time\|user]` | Take the voice away and cut their audio (no argument: everyone) |
| `multivoice <on\|off>` | One speaker per team at the same time; lines still play one at a time |
| `channel <canal\|off>` | Connect to a channel's chat (name or pasted link), or disconnect |
| `tint <time> <#rrggbb\|off> [0-1]` | Team goblin tint color and strength |
| `teamvoice <time\|default> <perfil\|none>` | Voice profile a team speaks with (Voz tab) |
| `engine <server\|sapi\|dummy>` | Switch the TTS engine |
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

## Voice (TTS server + "Voz" tab)

The voice runs in a separate **TTS server** (`tts_server/`): its own Python environment with PyTorch
(CUDA) and OmniVoice, which loads the model on the GPU once. The backend starts it automatically and
stops it on exit (`[tts.server] autostart`). If one is already running at `[tts.server] url`, it is used
instead.

```
backend (goblin_yapper) ──HTTP──► TTS server (tts_server/server.py) ──► engine (engines/omnivoice_engine.py)
     /api/tts/* proxy                profiles, pipeline, params              OmniVoice on the GPU
```

The **Voz** tab in the panel (`/panel#voz`):

- **status**: model loading / ready, GPU and VRAM, restart button, engine switch (OmniVoice / Windows / test)
- **new profile**: drag a `.wav` → prepare (mono, 24 kHz, trim silence, normalize, max length) →
  transcribe with Whisper → review/edit the transcript → create. The voice clone is computed once and saved.
- **profiles**: play the reference, edit name/transcript (re-creates the voice), per-profile parameters, delete
- **parameters**: every OmniVoice parameter (language, speed, decoding steps, guidance, denoise, ...),
  as global defaults or overrides for one profile
- **test**: type a line, pick a profile, hear it (uses the form's unsaved values)
- **team voices**: which profile each team speaks with; teams without one use the default

Profiles live in the data folder: `tts\profiles\<id>\` (`reference.wav`, `profile.json`, `omnivoice.pt`).
The `.wav` and transcript are the source, so another engine can rebuild its own cache from them.
Server log: `tts\tts-server.log`.

**Changing the TTS engine later**: add `tts_server/engines/<name>_engine.py` with an `Engine` subclass
(`params()`, `transcribe()`, `build_profile()`, `synthesize()`; see `engines/base.py`), register it in
`engines/__init__.py`, and set `[tts.server] engine = "<name>"`. The Voz tab builds its form from the
engine's `params()`, so nothing in the app needs to change.

Other engines (`[tts] engine` in `config.toml`, or the switch in the Voz tab):

| engine   | what it is                                                     |
|----------|----------------------------------------------------------------|
| `server` | the TTS server above (default)                                 |
| `sapi`   | Windows voices (`[tts.sapi] voice = "Microsoft Maria Desktop"` for pt-BR) |
| `dummy`  | babble tones, for testing without a GPU                         |
| `custom` | your own Python function, see `scripts/my_tts.py`               |

## License

Goblin Yapper's own code is **MIT** (see [LICENSE](LICENSE)). It does not include third-party model
weights or library code; those are installed by `tts_server/setup.ps1` or downloaded on first use, and
keep their own licenses. See [NOTICE](NOTICE) for the full attributions.

- **OmniVoice** (k2-fsa): code Apache-2.0; the **pre-trained model is CC-BY-NC — non-commercial use only**.
  Using the OmniVoice voice on monetized streams may count as commercial use; check the model's terms.
  The engine is swappable (see "Changing the TTS engine later") if you need a commercially licensed model.
- The OmniVoice model's audio tokenizer: **Built with Higgs Materials licensed from Boson AI USA, Inc.,
  Copyright Boson AI USA, Inc., All Rights Reserved and Meta Llama 3 licensed under the Meta Llama 3
  Community License, Copyright Meta Platforms, Inc., All Rights Reserved.** Agreements in
  [third_party/](third_party/); use must follow the
  [Meta Llama 3 Acceptable Use Policy](https://llama.meta.com/llama3/use-policy).
- **Whisper** (OpenAI, transcription): MIT.

Only clone voices with the speaker's permission.
