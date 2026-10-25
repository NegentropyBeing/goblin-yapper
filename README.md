<p align="center"><img src="docs/banner.png" alt="Goblin Yapper banner with Goburin, the Goblin Yapper goblin" width="720"></p>

# Goblin Yapper

> **Português:** a versão em português deste README está em [README.pt-BR.md](README.pt-BR.md).

A Twitch streaming app: chat joins a queue with `!joinsort`, you sort them into teams, and whoever you pick
**gets the voice**: their messages are read aloud and their team's goblin talks on your OBS scene.

- **Team sorter**: up to 4 balanced teams (blue, green, purple, yellow); drag
  people between teams, re-sort, and late joiners are added automatically.
- **Voice**: give the voice to a random person on a team, the next one on the same team, or a specific person.
  Voices can be cloned from your own audio (OmniVoice, running on your GPU).
- **OBS overlay**: one goblin per team, tinted with the team color, that moves while it talks. Use the built-in
  goblin or your own images (idle png + talking gif).

Chat is read anonymously: no Twitch login needed. The interface comes in English and Portuguese (pt-BR): pick
one with **Language** at the top right of the panel (until you do, it follows your Windows language).

## Download and install

1. Download the `.msi` installer in your language from the [releases page](https://github.com/NegentropyBeing/goblin-yapper/releases/latest):
   `…_x64_en-US.msi` (English) or `…_x64_pt-BR.msi` (Portuguese). Both install the same app; the file only sets the
   language of the installer itself. The app's language is chosen separately, in the panel.
2. Run it. The installer is unsigned, so Windows SmartScreen may warn you: click **More info → Run anyway**.

Requirements:
- Windows 10 or 11 (64-bit).
- For the cloned voice (OmniVoice): an NVIDIA GPU is recommended (tested on an RTX 5070) and about 11 GB of free
  disk space. Without a GPU it runs on the CPU, slowly. Windows voices work on any PC.

## How to use

1. **Connect to chat**: type the channel name (or paste its link) in the **twitch channel** field and click
   **Connect**.
2. **Build the teams**: pick how many teams, click **Open queue** and ask chat to type `!joinsort`.
   Click **Sort**. After that, anyone who joins goes straight to the smallest team.
3. **Give the voice**: click **🎤 Draw voice** on a team (random person from that team) or the 🎤 next to a
   name (that person). **⏭ Next** passes the voice to someone else on the same team and **⏹ Stop** takes it
   from the team; **Stop voice**, at the top, stops everything.
   With **several teams at the same time** on, each team can have a speaker; lines play one
   at a time. **🔊 Test voice**, on each team, makes that team's goblin say a fixed phrase in the
   team's voice.
4. **Add it to OBS**: open **OBS overlay and goblin images**, copy each team's URL and add a
   **Browser Source** in OBS for each one.
5. **Set up the voice** (**Voice** tab): the first time, click **Install voice server**.
   It downloads everything it needs (~3.5 GB, plus ~3 GB for the model on first start); no Python install
   needed. Then create voice profiles and choose which profile each team uses.

### Chat commands

| command | what it does |
|---------|--------------|
| `!joinsort` or `!joinsorting` | Join the queue (only while it's open). After the sort, join the smallest team directly. |
| `!leavesort` | Leave the queue or team. |

Whoever has the voice doesn't type a command: their normal messages are read. Messages starting with `!`, links
and emotes are skipped, and at most 5 messages wait in line; the rest are dropped. Speech tags work in chat too:
`that was close [laughter]` makes the goblin laugh.

### OBS

- **One source per team**: `http://127.0.0.1:8765/overlay?team=azul` (`azul`, `verde`, `roxo` or `amarelo` are the team ids, whatever the
  interface language; transparent background; the app must be open). Each source shows its team's goblin, which only moves and only plays sound for **that team's** lines.
- **Main source** (optional): `http://127.0.0.1:8765/overlay` shows whoever is speaking and plays the lines of
  teams that have no source of their own, and of people without a team.
- Each line plays in exactly one source, so sound is never doubled. In the panel, a green dot next to each URL
  means that source is open in OBS. With no source open, the app itself plays the line (handy for testing).
- Enable "Control audio via OBS" on each source to put each team on its own mixer channel.
- **Size**: the goblin fills the whole source, with a strip at the bottom for the name. Set the size with the
  source's own width and height in OBS; for the built-in goblin, 640 × 400 fits well (640 × 360 without the name).
- Other options: `?label=0` (hide the name and its strip), `?audio=0` (silent source), `?size=400` (goblin in a
  fixed 400 px box instead of filling the source).
- The panel also works as an OBS custom dock: `http://127.0.0.1:8765/panel`.

### Goblin images

**OBS overlay and goblin images** has a **Default** row and one row per team, each with a slot for
the png (idle) and one for the gif (talking): drop the images in or click to choose.

- **Default**: used by every team without images of its own. Each team gets this goblin tinted with its color; a
  neutral or grayish goblin tints best.
- **Per team**: a png + gif pair just for that team. The team's tint is still applied on top: to show the art as
  drawn, slide that team's tint bar down to zero.
- Without images, the built-in goblin is used.

### Voice profiles

In the **Voice** tab, drop a `.wav` of the voice to clone. The app prepares the audio (trims silence, normalizes),
transcribes it with Whisper, and you review the transcript before creating the profile. You can test lines,
tune every OmniVoice parameter (language, speed, ...) for all profiles or just one, and pick each team's voice.
Windows voices are also available as an alternative.

**Voice style and speech tags.** The **＋** next to *Voice style* lists the terms OmniVoice understands (gender,
age, pitch, whisper, English accent), one of each kind; it only takes effect on lines spoken without a voice
profile. **＋ tag** next to the test boxes and the transcript inserts a speech tag such as `[laughter]` or `[sigh]`,
which the voice turns into the sound.

**Only clone voices with the speaker's permission.**

## Where your data lives

- Settings, images, voice profiles and log: `%APPDATA%\com.goblinyapper.desktop\` (the panel shows it under
  **Data folder**).
- Voice server: `%LOCALAPPDATA%\GoblinYapper\voice-runtime\`; the model lives in the Hugging Face cache.
- Uninstalling the app keeps these folders. Delete them to remove everything.

## Development

To run from source, build the installer, use the HTTP API or swap the TTS engine, see
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). Original design notes: [docs/SPEC.md](docs/SPEC.md).

Testing the project without being a programmer? Follow the [step-by-step test guide](docs/TESTE.md).

## License

Goblin Yapper's code is **MIT** (see [LICENSE](LICENSE)). Third-party models and libraries are downloaded
separately and keep their own licenses; see [NOTICE](NOTICE).

- **OmniVoice** (k2-fsa): code Apache-2.0; the **pre-trained model is CC-BY-NC, non-commercial use only**.
  Using the OmniVoice voice on monetized streams may count as commercial use; check the model's terms.
  Windows voices don't have this restriction.
- The OmniVoice model's audio tokenizer: **Built with Higgs Materials licensed from Boson AI USA, Inc.,
  Copyright Boson AI USA, Inc., All Rights Reserved and Meta Llama 3 licensed under the Meta Llama 3
  Community License, Copyright Meta Platforms, Inc., All Rights Reserved.** Agreements in
  [third_party/](third_party/); use must follow the
  [Meta Llama 3 Acceptable Use Policy](https://llama.meta.com/llama3/use-policy).
- **Whisper** (OpenAI, transcription): MIT.
