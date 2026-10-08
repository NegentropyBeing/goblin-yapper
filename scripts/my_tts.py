"""Template for plugging your own TTS / voice-cloning script in.

Set in config.toml:
    [tts]
    engine = "custom"
    [tts.custom]
    path = "scripts"
    callable = "my_tts:synthesize"
    load = "my_tts:load"

`voice` is the merged [tts.voices.default] + [tts.voices.<team>] table, so each
team's goblin can have its own cloned voice (ref_audio / ref_text / anything you want).
"""

model = None


def load():
    """Called once at startup, in a worker thread. Load the model onto the GPU here."""
    global model
    # import torch
    # from omnivoice import OmniVoice
    # model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map="cuda:0", dtype=torch.float16)


def synthesize(text: str, voice: dict):
    """Return WAV bytes, or (samples, sample_rate) with float samples in [-1, 1]."""
    # audio = model.generate(text=text, ref_audio=voice.get("ref_audio"), ref_text=voice.get("ref_text"))
    # return audio[0], 24000
    raise NotImplementedError("edite scripts/my_tts.py")
