"""'Best for this PC' model recommendations (core.hardware.recommend_models)
and the dialog that shows them."""
from __future__ import annotations

import pytest

from core import hardware as hw
from core import model_manager as mm


def _gpu(memory_mb: int) -> hw.CudaStatus:
    return hw.CudaStatus(
        usable=True, gpu_present=True, gpu_name="NVIDIA GeForce RTX 5060 Laptop GPU",
        memory_mb=memory_mb, compute_types=("float16",),
    )


_CPU_ONLY = hw.CudaStatus(usable=False, gpu_present=False, reason="No NVIDIA CUDA GPU was found.")


@pytest.mark.parametrize(
    "memory_mb, expected",
    [
        (8151, ["large-v3-turbo", "large-v3"]),   # RTX 5060 laptop, 8 GB
        (24576, ["large-v3-turbo", "large-v3"]),
        (6144, ["large-v3-turbo"]),               # one pick: turbo fits, large is tight
        (2048, ["small", "medium"]),
        (0, ["large-v3-turbo"]),                  # unknown VRAM: the safe large model
    ],
)
def test_gpu_picks_follow_vram(memory_mb, expected):
    assert [p.slug for p in hw.recommend_models(_gpu(memory_mb))] == expected


def test_cpu_picks_for_a_typical_computer():
    picks = hw.recommend_models(_CPU_ONLY, ram_gb=16, cpu_cores=8)
    assert [(p.kind, p.slug) for p in picks] == [("fastest", "small"), ("accurate", "large-v3-turbo")]


@pytest.mark.parametrize("ram_gb, cores", [(4, 8), (16, 2)])
def test_cpu_picks_for_a_modest_computer(ram_gb, cores):
    picks = hw.recommend_models(_CPU_ONLY, ram_gb=ram_gb, cpu_cores=cores)
    assert [p.slug for p in picks] == ["base", "small"]


def test_unusable_gpu_is_advised_like_a_cpu():
    status = hw.CudaStatus(usable=False, gpu_present=True, memory_mb=8151, reason="cuBLAS missing")
    picks = hw.recommend_models(status, ram_gb=16, cpu_cores=8)
    assert [p.slug for p in picks] == ["small", "large-v3-turbo"]


def test_every_recommended_slug_is_in_the_built_in_catalog():
    cases = [_gpu(m) for m in (0, 2048, 6144, 8151)]
    slugs = {p.slug for s in cases for p in hw.recommend_models(s)}
    for ram, cores in ((4, 2), (16, 8)):
        slugs |= {p.slug for p in hw.recommend_models(_CPU_ONLY, ram_gb=ram, cpu_cores=cores)}
    assert slugs <= set(mm.MODEL_REGISTRY)


def test_system_ram_is_read():
    assert hw.system_ram_gb() > 0


def test_dialog_shows_the_picks_and_applies_one(monkeypatch, tmp_path):
    tk = pytest.importorskip("tkinter")
    monkeypatch.setattr(hw, "cuda_status", lambda: _gpu(8151))
    monkeypatch.setattr(mm, "model_downloaded", lambda cfg, slug: slug == "large-v3-turbo")

    from app.dialogs.model_advisor import ModelAdvisorDialog

    root = tk.Tk()
    root.withdraw()
    try:
        labels = dict(mm.catalog_models({}))
        applied: list[str] = []

        class _App:
            app_config: dict = {"whisper_model": "small", "hub_folder": str(tmp_path)}
            transcribe_model_var = tk.StringVar(master=root, value=labels["small"])

            def _on_model_selected(self) -> None:
                slug = {v: k for k, v in labels.items()}[self.transcribe_model_var.get()]
                applied.append(slug)
                self.app_config["whisper_model"] = slug

        dlg = ModelAdvisorDialog(root, _App())  # type: ignore[arg-type]
        dlg.withdraw()
        dlg._thread.join(timeout=10)
        import time
        deadline = time.time() + 5
        while time.time() < deadline and not dlg.picks_frame.winfo_children():
            dlg.update()
            time.sleep(0.02)
        cards = dlg.picks_frame.winfo_children()
        assert [c.cget("text") for c in cards] == ["Fastest", "Most accurate"]
        assert "models run on the GPU" in dlg.summary_var.get()
        dlg._use("large-v3")
        assert applied == ["large-v3"]
    finally:
        root.destroy()
