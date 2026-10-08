from .base import Engine, Param


def get_engine(name: str):
    if name == "omnivoice":
        from .omnivoice_engine import OmniVoiceEngine

        return OmniVoiceEngine
    raise ValueError(f"engine desconhecida: {name}")


__all__ = ["Engine", "Param", "get_engine"]
