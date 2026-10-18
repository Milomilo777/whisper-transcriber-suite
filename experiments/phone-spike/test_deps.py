"""Optional runtime availability check. No installs, downloads or eager imports."""
import importlib.util


def availability():
    return {name: importlib.util.find_spec(name) is not None
            for name in ("vosk", "sherpa_onnx", "datasets", "soundfile", "librosa", "numpy")}


if __name__ == "__main__":
    for name, present in availability().items():
        print(f"{name}: {'installed' if present else 'unavailable (optional)'}")
