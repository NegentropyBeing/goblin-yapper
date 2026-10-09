<p align="center"><img src="docs/goburin.png" alt="Goburin, the Goblin Yapper goblin" width="280"></p>

# Goblin Yapper

> **English:** the English version of this README is [further down this page](#english).

Sorteio de times para a Twitch + overlay de "goblin" com TTS para o OBS. Notas de design originais:
[docs/SPEC.md](docs/SPEC.md).

```
Chat da Twitch (IRC anônimo) ──► sorteio de times (!joinsort) ──► controle de voz (quem fala)
                                                                     │ mensagens de quem está com a voz
                                                                     ▼
Fonte de navegador do OBS ◄── WebSocket + /audio/<id>.wav ◄── engine de TTS (dummy | sapi | omnivoice | custom)
(goblin png ⇄ gif + tinta)

App desktop (Tauri) ── inicia ──► backend Python (sidecar exe) ── serve ──► /panel  /overlay  /api
```

## Instalação e execução (PowerShell)

Todos os comandos são de PowerShell, executados na pasta do projeto (a raiz do repositório).

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

**Abrir o app**

```powershell
# último build compilado (debug)
& ".\app\src-tauri\target\debug\goblin-yapper.exe"

# build de release (gerado pelo build.ps1)
& ".\app\src-tauri\target\release\goblin-yapper.exe"
```

Feche o app antes de reiniciar o backend: o servidor que estiver ocupando a porta 8765 é o que será usado.

**Recompilar o app sem gerar o instalador**

```powershell
cd app; npx tauri build --debug --no-bundle; cd ..   # -> app\src-tauri\target\debug\goblin-yapper.exe
cd app; npx tauri dev; cd ..                          # ou: compila e abre em um passo só
```

Necessário depois de mudar o ícone, a tela de carregamento (`app/src/index.html`) ou o `main.rs`.
Mudanças no painel e no overlay só exigem reiniciar o backend a partir do código-fonte.

**Gerar o instalador (.msi)**

```powershell
.\build.ps1
# -> app\src-tauri\target\release\bundle\msi\Goblin Yapper_0.1.0_x64_pt-BR.msi
```

**Rodar os testes**

```powershell
.venv\Scripts\python -m pytest
```

**Logs e dados**

```powershell
Get-Content "$env:APPDATA\com.goblinyapper.desktop\goblin-yapper.log" -Tail 30   # log do backend
explorer "$env:APPDATA\com.goblinyapper.desktop"                                 # config, settings, assets
```

## App desktop (instalador para Windows)

O `build.ps1` roda os testes, congela o backend com o PyInstaller em
`app/src-tauri/binaries/goblin-yapper-server-<target>.exe` e depois o `tauri build` empacota o app,
o backend e o instalador do WebView2 em um `.msi`. Requer Python 3.13, Rust e Node.

App instalado:
- a janela é o painel do operador (`/panel`): arrastar chatters entre times, botões de voz, seletores de tinta,
  upload das imagens do goblin e URLs do overlay para copiar no OBS.
- os dados do usuário ficam em `%APPDATA%\com.goblinyapper.desktop\` — `config.toml`, `settings.json`
  (alterações feitas no painel), `assets\`, `tts\` (perfis de voz, log do servidor de TTS), `goblin-yapper.log`.
- **voz, primeira execução**: o instalador é pequeno e só traz o código do servidor de TTS. Na aba **Voz**,
  clique em **Instalar servidor de voz**: ele baixa o [uv](https://github.com/astral-sh/uv) (versão fixa, checksum
  verificado), um Python 3.13 independente, o PyTorch com CUDA 12.8 e o OmniVoice (~3,5 GB de download, ~8 GB em
  disco) em `%LOCALAPPDATA%\GoblinYapper\voice-runtime\` e depois inicia o servidor. O modelo de voz (~3 GB) é
  baixado para o cache do Hugging Face na primeira vez que o servidor inicia. Não é preciso ter Python instalado
  no sistema.
- desinstalar o app mantém o runtime de voz e os seus dados; apague `%LOCALAPPDATA%\GoblinYapper\` e
  `%APPDATA%\com.goblinyapper.desktop\` para removê-los.
- um backend rodando a partir do código-fonte continua funcionando junto: inicie-o **antes** de abrir o app, e o
  app se conecta a ele na porta 8765 em vez de iniciar o seu próprio.

## Comandos do chat da Twitch

O que os espectadores digitam no chat:

| comando | o que faz |
|---------|-----------|
| `!joinsort` ou `!joinsorting` | Entra na fila. Só funciona com a fila **aberta**. Depois do sorteio, quem entra atrasado vai direto para o menor time (`auto_assign_late`). |
| `!leavesort` | Sai da fila ou do time. |

Quem **está com a voz** não digita comando: as mensagens normais dessa pessoa no chat são lidas pelo TTS e o
goblin do time dela fala. Antes da leitura:

- mensagens que começam com `!` são ignoradas (`skip_commands`)
- links e emotes da Twitch são removidos
- no máximo 5 mensagens ficam esperando; as que passarem disso são descartadas (`max_queue`)

Os nomes dos comandos e os limites ficam no `config.toml` (`[twitch]` e `[tts]`).

## Comandos do operador

O que você usa para conduzir a dinâmica: os botões do painel, o console (`help`, quando o backend roda a partir
do código-fonte em um terminal) e a API HTTP usam os mesmos comandos. `<time>` é `azul`, `verde`, `roxo` ou
`amarelo`.

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
| `state` | Mostra a fila, os times e quem está com a voz |

O painel roda em `http://127.0.0.1:8765/panel` (também funciona no navegador ou como dock personalizado do OBS).
API HTTP:

```
POST /api/command   {"command": "sort"}
GET  /api/state
WS   /ws            (envios de state / speak / idle / stop / assets)
```

## OBS

Adicione uma **Fonte de navegador** em `http://127.0.0.1:8765/overlay` (fundo transparente).
Ative "Controlar áudio pelo OBS" se quiser o TTS em um canal próprio do mixer.

- `?team=azul&audio=0` para fixar um goblin por time (uma fonte por time); deixe **uma** fonte com o áudio ligado.
- `?size=400`, `?label=0`.

As imagens do goblin ficam em `assets/`: `goblin.png` (parado) + `goblin.gif` (falando). Cada time recebe o
mesmo goblin tingido com a sua cor, definida por time no `config.toml` (`[teams.tint.azul] color / strength`)
ou ao vivo com `tint azul #1e40ff 0.7` / `tint azul off`. Um goblin neutro/acinzentado fica melhor tingido.
Imagens por time (`azul.png` / `azul.gif`), se existirem, substituem as compartilhadas.
Sem imagens, é usado o goblin goburin embutido (desenhado em SVG, tingido por time).

## Voz (servidor de TTS + aba "Voz")

A voz roda em um **servidor de TTS** separado (`tts_server/`): um ambiente Python próprio com PyTorch (CUDA) e
OmniVoice, que carrega o modelo na GPU uma única vez. O backend o inicia automaticamente e o encerra ao sair
(`[tts.server] autostart`). Se já houver um rodando em `[tts.server] url`, esse é usado.

```
backend (goblin_yapper) ──HTTP──► servidor de TTS (tts_server/server.py) ──► engine (engines/omnivoice_engine.py)
     proxy /api/tts/*                 perfis, pipeline, parâmetros                  OmniVoice na GPU
```

A aba **Voz** do painel (`/panel#voz`):

- **status**: modelo carregando / pronto, GPU e VRAM, botão de reiniciar, troca de engine (OmniVoice / Windows / teste)
- **novo perfil**: arraste um `.wav` → preparar (mono, 24 kHz, cortar silêncio, normalizar, duração máxima) →
  transcrever com o Whisper → revisar/editar a transcrição → criar. O clone de voz é calculado uma vez e salvo.
- **perfis**: ouvir a referência, editar nome/transcrição (recria a voz), parâmetros por perfil, excluir
- **parâmetros**: todos os parâmetros do OmniVoice (idioma, velocidade, passos de decodificação, guidance,
  denoise, ...), como padrões globais ou ajustes de um perfil específico
- **teste**: digite uma frase, escolha um perfil e ouça (usa os valores do formulário, mesmo sem salvar)
- **vozes dos times**: qual perfil cada time usa; times sem perfil usam o padrão

Os perfis ficam na pasta de dados: `tts\profiles\<id>\` (`reference.wav`, `profile.json`, `omnivoice.pt`).
O `.wav` e a transcrição são a fonte, então outra engine pode reconstruir o próprio cache a partir deles.
Log do servidor: `tts\tts-server.log`.

**Trocar a engine de TTS no futuro**: adicione `tts_server/engines/<nome>_engine.py` com uma subclasse de
`Engine` (`params()`, `transcribe()`, `build_profile()`, `synthesize()`; veja `engines/base.py`), registre-a em
`engines/__init__.py` e defina `[tts.server] engine = "<nome>"`. A aba Voz monta o formulário a partir do
`params()` da engine, então nada no app precisa mudar.

Outras engines (`[tts] engine` no `config.toml`, ou a troca na aba Voz):

| engine   | o que é                                                         |
|----------|-----------------------------------------------------------------|
| `server` | o servidor de TTS acima (padrão)                                |
| `sapi`   | vozes do Windows (`[tts.sapi] voice = "Microsoft Maria Desktop"` para pt-BR) |
| `dummy`  | bipes que imitam fala, para testar sem GPU                      |
| `custom` | sua própria função Python, veja `scripts/my_tts.py`             |

## Licença

O código do próprio Goblin Yapper é **MIT** (veja [LICENSE](LICENSE)). Ele não inclui pesos de modelos nem
código de bibliotecas de terceiros; esses são instalados pelo `tts_server/setup.ps1` ou baixados no primeiro
uso, e mantêm as suas próprias licenças. Veja o [NOTICE](NOTICE) para as atribuições completas.

- **OmniVoice** (k2-fsa): código Apache-2.0; o **modelo pré-treinado é CC-BY-NC — somente uso não comercial**.
  Usar a voz do OmniVoice em lives monetizadas pode contar como uso comercial; confira os termos do modelo.
  A engine é substituível (veja "Trocar a engine de TTS no futuro") se você precisar de um modelo com licença
  comercial.
- O tokenizador de áudio do modelo OmniVoice (atribuição exigida, mantida no original em inglês):
  **Built with Higgs Materials licensed from Boson AI USA, Inc., Copyright Boson AI USA, Inc., All Rights
  Reserved and Meta Llama 3 licensed under the Meta Llama 3 Community License, Copyright Meta Platforms, Inc.,
  All Rights Reserved.** Os contratos estão em [third_party/](third_party/); o uso deve seguir a
  [Política de Uso Aceitável do Meta Llama 3](https://llama.meta.com/llama3/use-policy).
- **Whisper** (OpenAI, transcrição): MIT.

Só clone vozes com a permissão de quem fala.

---

# English

Twitch team sorter + TTS "goblin" overlay for OBS. Original design notes: [docs/SPEC.md](docs/SPEC.md).

```
Twitch chat (anonymous IRC) ──► team sorter (!joinsort) ──► voice controller (who speaks)
                                                                 │ messages from the active chatter
                                                                 ▼
OBS browser source ◄── WebSocket + /audio/<id>.wav ◄── TTS engine (dummy | sapi | omnivoice | custom)
(goblin png ⇄ gif + tint)

Desktop app (Tauri) ── starts ──► Python backend (sidecar exe) ── serves ──► /panel  /overlay  /api
```

## Setup and run (PowerShell)

All commands are PowerShell, run from the project folder (the repository root).

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
