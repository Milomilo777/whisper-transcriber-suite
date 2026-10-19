# Physical Android validation (not performed)

The original Linux VM is not a phone. The current integration tests ran on a
Windows AMD64 host with fake engines. No physical Android timing, WER, RAM, or
thermal measurements exist. The measured top two engine/model/quant combinations
are **unknown**. Desktop x86 speed is only a proxy: ARM SIMD/NEON, big.LITTLE and
thermal throttling can change both absolute speed and the order.

The commands below run two fully specified **provisional** combinations,
`whisper.cpp-tiny-q5_1` and `whisper.cpp-base-q5_1`. They demonstrate the identical
runner on a real phone; they are not a measured top-two recommendation. After a
real desktop study, replace the engine list with its two leading candidates.
If either is Vosk or sherpa-onnx, its ARM Python/native runtime packaging remains
unverified; this guide does not claim unavailable Termux wheels exist.

## Prepare public assets on the desktop

Complete the real setup and data commands in the parent README in a later,
authorized measurement session. Keep `data/` (including refs.tsv and manifest.json)
and `models/ggml-tiny-q5_1.bin`, `models/ggml-base-q5_1.bin` and the SHA256 manifest.
Use the same WAVs and references on desktop and phone. Do not transfer the
maintainer's private recordings from this PC.

Copy this `phone-spike` folder to the phone's Download folder over USB. Include
the Python files, `engines/`, `metrics/`, public `data/` and the two model files;
exclude the desktop `.venv/`, `build/`, test scratch and results. Do not copy
desktop binaries or install a desktop wheel on ARM.

## Termux commands on a physical ARM64 phone

Start a fresh Termux shell in its normal initial directory. Termux must have a
working package repository. These are phone provisioning/build commands, not
commands run during this integration review.

```sh
pkg update
pkg install python clang cmake git make
termux-setup-storage
cp -R storage/downloads/phone-spike phone-spike
cd phone-spike
python setup.py --build
python bench.py --audio-dir data --refs data/refs.tsv --engines whisper.cpp-tiny-q5_1,whisper.cpp-base-q5_1 --threads 1,4 --out results/android-fa-run1.json
python summarize.py --json results/android-fa-run1.json --out results/ANDROID-SUMMARY-run1.md
python bench.py --audio-dir data --refs data/refs.tsv --engines whisper.cpp-tiny-q5_1,whisper.cpp-base-q5_1 --threads 1,4 --out results/android-fa-run2.json
python summarize.py --json results/android-fa-run2.json --out results/ANDROID-SUMMARY-run2.md
```

Grant the requested shared-storage permission for the copy. Run from Termux's
private directory, not shared storage, so the compiled CLI can execute.
The CLI-only runs need no vosk/sherpa/datasets/numpy packages. The setup builds
whisper.cpp at v1.7.1 on the device; it does not build an Android app. Do not run
`setup.py --all` here, since its desktop optional-package set is not validated
for Termux.

Collect device metadata in that same folder:

```sh
getprop ro.product.model
getprop ro.soc.model
uname -m
python -c "import json; from runtime import environment_info; print(json.dumps(environment_info(), indent=2))"
```

Record model/SoC, Android and Termux versions, power/thermal conditions and
whether the phone was cooling between runs in `results/DEVICE.md`. Keep both
raw runs; do not select only the faster one. Inspect FAILED/UNAVAILABLE statuses,
two sample pairs, long-form errors, repetition/deletions, RAM measurement source,
and thread behavior. The same CLI-reload timing caveat from the parent README
still applies on the phone; these commands do not create resident-model parity.

These steps and upstream Android bindings have not been executed/validated here.
A maintainer must verify on real hardware before any Android ranking or release.
