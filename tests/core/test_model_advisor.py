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


_RAM_GRID = [round(0.5 + 0.1 * i, 1) for i in range(0, 160)]  # 0.5 .. 16.4 GB


@pytest.mark.parametrize("ram_gb", _RAM_GRID)
def test_the_advisor_never_offers_a_model_the_ram_ladder_would_shrink(ram_gb):
    """Quick start sizes its pick with fit_model_to_ram; the advisor must agree."""
    for pick in hw.recommend_models(_CPU_ONLY, ram_gb=ram_gb, cpu_cores=8):
        assert hw.fit_model_to_ram(pick.slug, ram_gb) == pick.slug


@pytest.mark.parametrize("ram_gb", [3.0, 3.5, 3.9, 4.0, 4.9])
@pytest.mark.parametrize("wanted", ["large-v3", "large-v3-turbo", "medium"])
def test_3_to_5_gb_gets_the_same_model_from_quick_start_and_the_advisor(ram_gb, wanted):
    """Both used to disagree: the advisor said small, Quick start's ladder said medium."""
    accurate = hw.recommend_models(_CPU_ONLY, ram_gb=ram_gb, cpu_cores=8)[-1].slug
    assert hw.fit_model_to_ram(wanted, ram_gb) == accurate == "small"


def test_the_weak_ram_line_is_the_smallest_ram_the_big_models_need():
    for slug in ("medium", "large-v3-turbo"):
        assert hw.fit_model_to_ram(slug, hw._WEAK_RAM_GB) == slug
        assert hw.fit_model_to_ram(slug, hw._WEAK_RAM_GB - 0.1) == "small"


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
    monkeypatch.setattr(hw, "device_choice_from_hardware_file", lambda: None)  # not this PC's file
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


def _open_dialog(monkeypatch, tmp_path, status, config):
    """Open the dialog on a fake app and return it after the check finished."""
    import time
    import tkinter as tk

    from app.dialogs.model_advisor import ModelAdvisorDialog

    monkeypatch.setattr(hw, "cuda_status", lambda: status)
    monkeypatch.setattr(hw, "device_choice_from_hardware_file", lambda: None)
    monkeypatch.setattr(mm, "model_downloaded", lambda cfg, slug: False)
    root = tk.Tk()
    root.withdraw()

    class _App:
        app_config = {"hub_folder": str(tmp_path), **config}
        transcribe_model_var = tk.StringVar(master=root, value="")

    dlg = ModelAdvisorDialog(root, _App())  # type: ignore[arg-type]
    dlg.withdraw()
    dlg._thread.join(timeout=10)
    deadline = time.time() + 5
    while time.time() < deadline and not dlg.picks_frame.winfo_children():
        dlg.update()
        time.sleep(0.02)
    return root, dlg


def test_dialog_follows_a_cpu_setting_even_with_a_gpu(monkeypatch, tmp_path):
    pytest.importorskip("tkinter")
    root, dlg = _open_dialog(monkeypatch, tmp_path, _gpu(24576), {"device": "cpu"})
    try:
        assert "models run on the GPU" not in dlg.summary_var.get()
        assert "CPU" in dlg.summary_var.get()
        assert [c.cget("text") for c in dlg.picks_frame.winfo_children()] == ["Fastest", "Most accurate"]
    finally:
        root.destroy()


def test_dialog_says_when_offline_instead_of_promising_a_download(monkeypatch, tmp_path):
    pytest.importorskip("tkinter")
    from core import offline

    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: True)
    root, dlg = _open_dialog(monkeypatch, tmp_path, _gpu(8151), {})
    try:
        texts = " ".join(
            str(w.cget("text")) for card in dlg.picks_frame.winfo_children()
            for w in card.winfo_children() if "text" in w.keys()
        )
        assert "Work offline is on" in texts
        assert "Downloads once on first use" not in texts
    finally:
        root.destroy()


def test_dialog_explains_when_the_catalog_has_none_of_the_picks(monkeypatch, tmp_path):
    pytest.importorskip("tkinter")
    monkeypatch.setattr(mm, "catalog_models", lambda cfg: [("tiny", "Tiny")])
    root, dlg = _open_dialog(monkeypatch, tmp_path, _gpu(8151), {})
    try:
        kids = dlg.picks_frame.winfo_children()
        assert len(kids) == 1
        assert "None of the recommended models" in str(kids[0].cget("text"))
    finally:
        root.destroy()
