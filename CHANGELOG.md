# Changelog

## Unreleased

- **Volume** slider (Goblin tab, next to the automatic options): how loud the goblins speak in OBS, and in the
panel when no OBS source is open. Applies right away, even to the line playing, and is saved in `settings.json`
(`overlay.volume`, 0–100, default 100). Command: `volume <0-100>`.

## v0.7.0

Windows installers: `Goblin Yapper_0.7.0_x64_en-US.msi` (English) and `Goblin Yapper_0.7.0_x64_pt-BR.msi`
(Portuguese).

- **Bilingual interface (English / Portuguese).** Pick the language with **Language** at the top right of the panel;
until you do, the panel follows the system language. The choice is stored in `settings.json` (`ui.language`) and
there is a new `language <en|pt-BR>` command. The text of the panel and the overlay lives in `web/i18n/*.json`;
`POST /api/command` now answers `{ok, key, params, output, state}` and notices and HTTP errors are a key plus
values, so a client can translate them. Logs and the console are in English.
- The chat status in `state.chat.status` is now `off | connecting | connected | reconnecting` (it was Portuguese).
- Documents come in pairs, English by default and `.pt-BR` for Portuguese: `README`, `docs/DEVELOPMENT` and
`docs/TESTE` (the test guide now exists in English).
- **Testar voz** / **Test voice** and the test box speak in the interface language (a `[tts] test_phrase` in your
`config.toml` still wins; remove it to follow the language). `POST /api/command` accepts an optional `language`.
- **The Windows installer comes in two files**, one per language: `Goblin Yapper_<version>_x64_en-US.msi` and
`Goblin Yapper_<version>_x64_pt-BR.msi` (`bundle.windows.wix.language` is a list now). Both install the same app; the
file only sets the language of the installer itself.

## v0.6.1

Windows installer: `Goblin Yapper_0.6.1_x64_pt-BR.msi`.

- Fixed: the voice server crashed on start in v0.6.0 (`No module named 'profiles'`) because the installer left
`profiles.py` out of the voice runtime, so the panel showed "o servidor de voz parou".
- If the voice server dies, its error output is now written to `tts-server.log`, where the panel points.
- Test that every `tts_server` module is shipped by the installer, to keep this from happening again.

## v0.6.0

Windows installer: `Goblin Yapper_0.6.0_x64_pt-BR.msi`.

- **Esconder o goblin dos times que estão sem voz** toggle (Goblin tab, under the OBS sources): a team's OBS
source shows its goblin only while someone on that team has the voice, or one of its lines is playing. Off by
default. Command: `hideidle <on|off>`.
- Refactor for all services. 

## v0.5.0

Windows installer: `Goblin Yapper_0.5.0_x64_pt-BR.msi`.

- **Tirar inativos** toggle (Goblin tab): chatters in the queue or in a team who write nothing in chat for N
minutes are removed automatically. Only counts while the chat is connected; the clocks restart on reconnect.
Command: `autoremove <on|off> [min]`.
- **Trocar quem tem a voz** toggle: after N minutes the voice goes to another random chatter of the same team,
once the line being spoken ends. Each team's speaker has its own clock in multi-voice mode. Command:
`autorotate <on|off> [min]`.
- **⏭ Pular fala** button: drops the one line in progress, whether stuck in generation or playing, and goes on
with the queue. The panel shows whose line is being generated or spoken. Command: `skip`. **Parar voz** now
also frees a generation in progress instead of waiting for it.
- Fixed: transcribing a reference clip failed with `ffmpeg was not found` on a PC without ffmpeg installed.
Transcription no longer needs ffmpeg.
- **Descarregar Whisper** button on the Voz tab, shown while Whisper is loaded: unloads the transcription model
right away and frees its VRAM (about 1.5 GB). It loads again by itself on the next transcription.
- **Much lower VRAM use by the voice server.** Creating a voice profile no longer spikes by 3 to 6 GB (it could
fill an 8 GB card), the memory a job used is given back to the GPU right after it instead of staying
reserved, and Whisper is unloaded as soon as the profile is created. Measured on OmniVoice: about 2 GB idle
and under 3 GB while speaking. The Voz tab now shows the model's own VRAM next to the whole card's.
- **Desligar modelo / Ligar modelo** button on the Voz tab: turns the OmniVoice model off (ending the voice
server process, which frees its VRAM) and back on without closing the app. It is on again at the next app start.
- **Per-team goblin images**: the panel now has a png + gif slot pair for each team, next to the shared
default pair. A team without its own images keeps using the default.
- **Per-team overlay audio**: each team's OBS source plays only that team's lines, so every team can have its
own mixer channel. The main source plays lines of teams without a source. Each line plays in exactly one
source (no doubled audio); with no source open, the app itself plays it.
- **Testar voz** button on each team: the team's goblin says a fixed phrase (`[tts] test_phrase`) through the
full voice pipeline, with that team's voice profile.
- The panel shows which OBS sources are connected; the tint slider is thinner.
- Team source URLs no longer need `&audio=0`. Existing sources that have it stay silent, as before.
- The overlay's goblin now fills the whole browser source (with a strip for the name) instead of sitting in a
fixed 360 px box, so the OBS source's bounds match the image. `?size=N` keeps the old fixed box.
- The built-in goblin's ear bite is a real transparent cut-out, as in the original drawing, instead of a white dot.
- Deleting a voice profile is now recorded in `tts\tts-server.log` (time, name and id).
- The Voz tab shows the folder the profiles are saved in ("Perfis salvos em: …"), as reported by the voice
server itself, so it is clear which data folder's profiles are listed.

## v0.1.0 — first release

Windows installer: `Goblin Yapper_0.1.0_x64_pt-BR.msi`.

**Twitch team sorter**

- Reads chat anonymously (no login); viewers join with `!joinsort` / `!joinsorting`, leave with `!leavesort`.
- 1–4 teams (azul, verde, roxo, amarelo), balanced random sort; late joiners go to the smallest team.
- Drag chatters between teams, re-sort, return everyone to the queue, clear.

**Voice**

- Give the voice to a random chatter of a team, the next one from the same team, or a specific chatter;
their messages are read aloud while they have it.
- Optional "vários times ao mesmo tempo": one speaker per team at once; their lines play one at a time,
and each team's overlay shows its own speaker.
- OmniVoice TTS server on the GPU, installed from the app on first use (Voz tab; ~3.5 GB download, ~8 GB on disk).
- Voice profiles from a `.wav`: trim/normalize → Whisper transcription → review → create.
- Every OmniVoice parameter, globally or per profile; test speech; one profile per team.
- Windows voices (SAPI) as an alternative engine.

**OBS overlay**

- Browser source with a goblin per team (built-in "goburin" or your own png/gif), tinted with the team color;
it talks while its team's audio plays.

**Known limitations**

- The OmniVoice model is licensed CC-BY-NC (non-commercial); see README → License.
- The installer is unsigned: Windows SmartScreen asks for confirmation ("More info → Run anyway").
- The voice runtime needs an NVIDIA GPU to be fast (tested on an RTX 5070); without one it runs on the CPU, slowly.