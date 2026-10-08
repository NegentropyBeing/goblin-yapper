# Changelog

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
