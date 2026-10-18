"""Single registry. Optional runtimes must only be imported in load()."""


class EngineUnavailable(RuntimeError):
    pass


class Engine:
    def __init__(self, name):
        self.name = name
        self.last_timing = {}

    def load(self, threads):
        raise NotImplementedError

    def transcribe(self, audio_path):
        raise NotImplementedError

    def get_info(self):
        return {}

    def unload(self):
        pass


REGISTRY = {}


def register(name):
    def decorator(cls):
        if name in REGISTRY:
            raise ValueError(f"Duplicate engine: {name}")
        REGISTRY[name] = cls
        return cls
    return decorator
