# Desenvolvimento

> **English:** this page in English: [DEVELOPMENT.md](DEVELOPMENT.md).

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
| `skip` | Pula a fala em andamento (travada na geração ou tocando); a fila de falas continua |
| `autoremove <on\|off> [min]` | Tira da fila e dos times quem ficar `min` minutos sem escrever no chat (só conta com o chat conectado) |
| `autorotate <on\|off> [min]` | Passa a voz para outra pessoa do mesmo time a cada `min` minutos, depois que a fala atual termina |
| `hideidle <on\|off>` | A fonte de cada time esconde o goblin enquanto ninguém do time tem a voz |
| `channel <canal\|off>` | Conecta ao chat de um canal (nome ou link colado) ou desconecta |
| `tint <time> <#rrggbb\|off> [0-1]` | Cor e intensidade da tinta do goblin do time |
| `teamvoice <time\|default> <perfil\|none>` | Perfil de voz com que um time fala (aba Voz) |
| `engine <server\|sapi\|dummy>` | Troca a engine de TTS |
| `test <time> <texto>` | Faz o goblin daquele time dizer uma frase de teste |
| `testvoice <time>` | O goblin do time diz a frase fixa (`[tts] test_phrase`) com a voz do time (botão **Testar voz**) |
| `language <en\|pt-BR>` | Idioma do painel (fica salvo em `settings.json`, em `ui.language`) |
| `state` | Mostra a fila, os times e quem está com a voz |

```
POST /api/command   {"command": "sort"}
GET  /api/state
WS   /ws            (envios de state / speak / idle / stop / assets / notice)
```

**Mensagens em dois idiomas.** O servidor não manda frases: manda uma chave e valores, e o painel traduz com o
idioma escolhido. A resposta de `POST /api/command` é
`{"ok": true, "key": "msg.sorted", "params": {"count": 3}, "output": "3 sorted", "state": {...}}`: `output` é
o mesmo texto em inglês (para `curl` e para o console). Os erros HTTP do app e os avisos (`{"type": "notice", ...}`)
seguem o mesmo formato (`key`, `params`, `text`). `state.language` é o idioma escolhido (`null` até o operador escolher).

**Quem toca cada fala.** Ao conectar no `/ws`, cada overlay envia
`{"type": "hello", "role": "overlay", "team": "azul" | null, "audio": true}` (o painel envia `role: "panel"`;
as miniaturas do painel usam `?preview=1` e não contam). Todo cliente recebe o `speak` de cada fala, mas só
um recebe `play: true` (`App.pick_player`): o overlay fixado no time da fala, senão o overlay principal, senão
um painel aberto. Esse cliente toca `url` e responde `{"type": "ended", "id": n}`. `state.overlays` lista as
fontes do OBS conectadas.

## Configuração

O `config.toml` da pasta de dados é criado a partir de `goblin_yapper/default_config.toml` na primeira execução.
Nele ficam os comandos do chat (`[twitch]`), os limites do TTS (`max_queue`, `skip_commands`), as cores padrão
das tintas (`[teams.tint.<time>]`) e as engines. As alterações feitas no painel (incluindo o idioma, `ui.language`) vão para o `settings.json`, para
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

## Idiomas da interface

Os textos do painel e do overlay ficam em `goblin_yapper/web/i18n/en.json` (o idioma de referência) e
`pt-BR.json`; `web/i18n.js` os carrega. No HTML use `data-i18n="chave"` (e `data-i18n-title`,
`data-i18n-placeholder`); no JavaScript, `t("chave", {valor: ...})`. As mensagens do servidor usam as mesmas
chaves (`msg.*`, `err.*`, `notice.*`, `http.*`, `tts.*`) via `goblin_yapper/i18n.py`.

Para criar um texto: acrescente a chave nos **dois** arquivos. `tests/test_i18n.py` falha se os arquivos tiverem
chaves diferentes, se uma página usar uma chave inexistente ou se o servidor mandar uma chave sem texto. Para um
terceiro idioma: um novo `<idioma>.json`, o código em `LANGUAGES` (`goblin_yapper/i18n.py` e `web/i18n.js`) e uma
opção no seletor do painel. Logs e o console ficam em inglês. O vocabulário comum está em
[GLOSSARY.md](../GLOSSARY.md). Os documentos existem em pares (`X.md` em inglês e `X.pt-BR.md`).
