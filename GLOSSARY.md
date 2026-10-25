# Goblin Yapper

A Twitch streaming companion: chat joins a queue, the operator sorts people into teams, and whoever is given the voice has their chat messages read aloud while their team's goblin talks on the OBS overlay. English is the reference language; the Portuguese (pt-BR) equivalent is given for every term so the interface and the docs stay consistent in both languages.

## Language

**Operator**:
The person running the app and the stream. pt-BR: _operador_.
_Avoid_: User, streamer, host

**Viewer**:
Anyone in the Twitch chat. Viewers are read anonymously; they never log in to the app. pt-BR: _espectador_.
_Avoid_: Chatter, user, participant

**Queue**:
The waiting list viewers join with `!joinsort` while it is open. pt-BR: _fila_.
_Avoid_: Lobby, waitlist

**Team**:
A group of viewers produced by a sort; there are up to four, each with its own colour and goblin. pt-BR: _time_.
_Avoid_: Group, squad

**Sort**:
Distributing the queued viewers into balanced teams at random. pt-BR: _sorteio_ (noun), _sortear_ (verb).
_Avoid_: Draw, shuffle, raffle

**Voice**:
The turn to speak: while a viewer holds it, their chat messages are read aloud and their team's goblin talks. Also the synthetic voice used to do the reading. pt-BR: _voz_ ("dar a voz" = give the voice).
_Avoid_: Mic, floor

**Voice profile**:
A synthetic voice cloned from a short reference recording and its transcript; each team can be given one. pt-BR: _perfil de voz_.
_Avoid_: Voice model, preset, variable

**Voice style**:
A set of descriptive terms (gender, age, pitch, accent, whisper) that shape how a synthetic voice sounds, at most one per kind. pt-BR: _estilo de voz_.
_Avoid_: Instruct, voice design, variable

**Speech tag**:
A bracketed mark in spoken text, such as `[laughter]` or `[sigh]`, that the voice turns into a non-verbal sound. pt-BR: _tag de fala_.
_Avoid_: Nonverbal tag, emote, variable

**Panel**:
The operator's control window, where the queue, teams, voice and settings are managed. pt-BR: _painel_.
_Avoid_: Dashboard, console

**Overlay**:
The browser-source page shown in OBS, with one goblin per team that moves while its team speaks. pt-BR: _overlay_.
_Avoid_: Scene, widget

**Interface language**:
The language the operator reads the panel in, chosen by the operator; independent of the language of the voice. pt-BR: _idioma da interface_.
_Avoid_: Locale, app language
