# Desenvolvimento

> **English:** the English version of this page is [further down](#development-english).

```
Chat da Twitch (IRC anônimo) ──► sorteio de times (!joinsort) ──► controle de voz (quem fala)
                                                                     │ mensagens de quem está com a voz
                                                                     ▼
Fonte de navegador do OBS ◄── WebSocket + /audio/<id>.wav ◄── engine de TTS (dummy | sapi | omnivoice | custom)
(goblin png ⇄ gif + tinta)

App desktop (Tauri) ── inicia ──► backend Python (sidecar exe) ── serve ──► /panel  /overlay  /api
```

## Instalação e execução (PowerShell)

Todos os comandos são de PowerShell, executados na raiz do repositório. Requer Python 3.13, Rust e Node.

**Primeira configuração**

```powershell
py -3.13 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
cd app; npm install; cd ..
.\tts_server\setup.ps1          # servidor de voz: PyTorch CUDA + OmniVoice (vários GB)
```

**Iniciar o backend a partir do código-fonte** (código Python mais recente; também inicia o servidor de TTS)

```powershell
.venv\Scripts\python -m goblin_yapper --data-dir "$env:APPDATA\com.goblinyapper.desktop"
```

Deixe-o rodando. O app o detecta na porta 8765 e o usa no lugar do backend embutido.
Sem o app, abra o painel no navegador: `http://127.0.0.1:8765/panel`.
Feche o app antes de reiniciar o backend: o servidor que estiver ocupando a porta 8765 é o que será usado.

**Abrir o app**

```powershell
& ".\app\src-tauri\target\debug\goblin-yapper.exe"     # último build de debug
& ".\app\src-tauri\target\release\goblin-yapper.exe"   # build de release (gerado pelo build.ps1)
```

**Recompilar o app sem gerar o instalador**

```powershell
cd app; npx tauri build --debug --no-bundle; cd ..   # -> app\src-tauri\target\debug\goblin-yapper.exe
cd app; npx tauri dev; cd ..                          # ou: compila e abre em um passo só
```

Necessário depois de mudar o ícone, a tela de carregamento (`app/src/index.html`) ou o `main.rs`.
Mudanças no painel e no overlay só exigem reiniciar o backend.

**Gerar o instalador (.msi)**

```powershell
.\build.ps1
# -> app\src-tauri\target\release\bundle\msi\Goblin Yapper_<versão>_x64_pt-BR.msi
```

O `build.ps1` roda os testes, congela o backend com o PyInstaller em
`app/src-tauri/binaries/goblin-yapper-server-<target>.exe` e depois o `tauri build` empacota o app, o backend e
o instalador do WebView2 em um `.msi`. O instalador só leva o código do servidor de TTS; o runtime de voz é
instalado pelo app na primeira vez (aba Voz), com o [uv](https://github.com/astral-sh/uv) (versão fixa, checksum
verificado), um Python 3.13 independente, PyTorch com CUDA 12.8 e OmniVoice.

**Rodar os testes**

```powershell
.venv\Scripts\python -m pytest
```

**Logs**

```powershell
Get-Content "$env:APPDATA\com.goblinyapper.desktop\goblin-yapper.log" -Tail 30   # backend
Get-Content "$env:APPDATA\com.goblinyapper.desktop\tts\tts-server.log" -Tail 30  # servidor de TTS
```

## Comandos do operador e API HTTP

Os botões do painel, o console (`help`, quando o backend roda num terminal) e a API HTTP usam os mesmos
comandos. `<time>` é `azul`, `verde`, `roxo` ou `amarelo`.

| comando | o que faz |
|---------|-----------|
| `open` / `close` | Abre ou fecha a fila do `!joinsort` |
| `teams <1-4>` | Número de times. Ao diminuir, os membros dos times removidos vão para os outros |
| `sort` | Sorteia todos da fila em times equilibrados |
| `resort` | Devolve todos à fila e sorteia de novo |
| `reset` | Devolve todos os membros dos times à fila |
| `clear` | Esvazia a fila e todos os times |
| `add <user>` | Adiciona alguém manualmente (funciona mesmo com a fila fechada) |
| `move <user> <time\|fila>` | Move alguém para outro time, ou de volta para a fila (`fila`) |
| `remove <user>` | Remove alguém completamente |
| `voice <time>` | Dá a voz a uma pessoa aleatória daquele time |
| `voice any` | Dá a voz a uma pessoa aleatória de qualquer time |
| `voice` / `next [time]` | Outra pessoa daquele time (padrão: o time de quem falou por último) |
| `give <user>` | Dá a voz a uma pessoa específica (ela não precisa estar em um time) |
| `stop [time\|user]` | Tira a voz e corta o áudio (sem argumento: de todos) |
| `multivoice <on\|off>` | Uma pessoa com a voz por time ao mesmo tempo; as falas continuam tocando uma de cada vez |
| `channel <canal\|off>` | Conecta ao chat de um canal (nome ou link colado) ou desconecta |
| `tint <time> <#rrggbb\|off> [0-1]` | Cor e intensidade da tinta do goblin do time |
| `teamvoice <time\|default> <perfil\|none>` | Perfil de voz com que um time fala (aba Voz) |
| `engine <server\|sapi\|dummy>` | Troca a engine de TTS |
| `test <time> <texto>` | Faz o goblin daquele time dizer uma frase de teste |
| `testvoice <time>` | O goblin do time diz a frase fixa (`[tts] test_phrase`) com a voz do time (botão **Testar voz**) |
| `state` | Mostra a fila, os times e quem está com a voz |

```
POST /api/command   {"command": "sort"}
GET  /api/state
WS   /ws            (envios de state / speak / idle / stop / assets)
```

**Quem toca cada fala.** Ao conectar no `/ws`, cada overlay envia
`{"type": "hello", "role": "overlay", "team": "azul" | null, "audio": true}` (o painel envia `role: "panel"`;
as miniaturas do painel usam `?preview=1` e não contam). Todo cliente recebe o `speak` de cada fala, mas só
um recebe `play: true` (`App.pick_player`): o overlay fixado no time da fala, senão o overlay principal, senão
um painel aberto. Esse cliente toca `url` e responde `{"type": "ended", "id": n}`. `state.overlays` lista as
fontes do OBS conectadas.

## Configuração

O `config.toml` da pasta de dados é criado a partir de `goblin_yapper/default_config.toml` na primeira execução.
Nele ficam os comandos do chat (`[twitch]`), os limites do TTS (`max_queue`, `skip_commands`), as cores padrão
das tintas (`[teams.tint.<time>]`) e as engines. As alterações feitas no painel vão para o `settings.json`, para
que o `config.toml` e os seus comentários fiquem intactos.

## Servidor de TTS e engines

A voz roda em um **servidor de TTS** separado (`tts_server/`): um ambiente Python próprio com PyTorch (CUDA) e
OmniVoice, que carrega o modelo na GPU uma única vez. O backend o inicia automaticamente e o encerra ao sair
(`[tts.server] autostart`). Se já houver um rodando em `[tts.server] url`, esse é usado.

```
backend (goblin_yapper) ──HTTP──► servidor de TTS (tts_server/server.py) ──► engine (engines/omnivoice_engine.py)
     proxy /api/tts/*                 perfis, pipeline, parâmetros                  OmniVoice na GPU
```

Os perfis ficam em `tts\profiles\<id>\` (`reference.wav`, `profile.json`, `omnivoice.pt`). O `.wav` e a
transcrição são a fonte, então outra engine pode reconstruir o próprio cache a partir deles.

**Trocar a engine de TTS**: adicione `tts_server/engines/<nome>_engine.py` com uma subclasse de `Engine`
(`params()`, `transcribe()`, `build_profile()`, `synthesize()`; veja `engines/base.py`), registre-a em
`engines/__init__.py` e defina `[tts.server] engine = "<nome>"`. A aba Voz monta o formulário a partir do
`params()` da engine, então nada no app precisa mudar.

Outras engines (`[tts] engine` no `config.toml`, ou a troca na aba Voz):

| engine   | o que é                                                         |
|----------|-----------------------------------------------------------------|
| `server` | o servidor de TTS acima (padrão)                                |
| `sapi`   | vozes do Windows (`[tts.sapi] voice = "Microsoft Maria Desktop"` para pt-BR) |
| `dummy`  | bipes que imitam fala, para testar sem GPU                      |
| `custom` | sua própria função Python, veja `scripts/my_tts.py`             |

---

<h1 id="development-english">Development (English)</h1>

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
| `channel <canal\|off>` | Connect to a channel's chat (name or pasted link), or disconnect |
| `tint <time> <#rrggbb\|off> [0-1]` | Team goblin tint color and strength |
| `teamvoice <time\|default> <perfil\|none>` | Voice profile a team speaks with (Voz tab) |
| `engine <server\|sapi\|dummy>` | Switch the TTS engine |
| `test <time> <texto>` | Make that team's goblin say a test line |
| `testvoice <time>` | The team's goblin says the fixed phrase (`[tts] test_phrase`) in the team's voice (**Testar voz** button) |
| `state` | Print queue, teams and who has the voice |

```
POST /api/command   {"command": "sort"}
GET  /api/state
WS   /ws            (state / speak / idle / stop / assets pushes)
```

**Who plays each line.** On connecting to `/ws`, each overlay sends
`{"type": "hello", "role": "overlay", "team": "azul" | null, "audio": true}` (the panel sends `role: "panel"`;
the panel's thumbnails use `?preview=1` and don't count). Every client gets the `speak` for each line, but only
one gets `play: true` (`App.pick_player`): the overlay pinned to the line's team, else the main overlay, else
an open panel. That client plays `url` and answers `{"type": "ended", "id": n}`. `state.overlays` lists the
connected OBS sources.

## Configuration

The data folder's `config.toml` is created from `goblin_yapper/default_config.toml` on first run. It holds the
chat commands (`[twitch]`), TTS limits (`max_queue`, `skip_commands`), default tint colors
(`[teams.tint.<team>]`) and the engines. Changes made in the panel go to `settings.json`, so `config.toml` and
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
