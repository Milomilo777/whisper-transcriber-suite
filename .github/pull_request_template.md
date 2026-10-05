## Summary

<!-- One-paragraph description of the change. What user-visible
or developer-visible thing is different after this PR? -->

## Test plan

- [ ] `python -m pyright app core` reports 0 errors
- [ ] `python -m pytest tests/ --ignore=tests/smoke` passes
- [ ] If UI code changed: ran the headless Tk smoke
      (`tests/smoke/test_app_headless.py`)
- [ ] If transcribe path changed: real-video smoke
      (`tests/smoke/test_exe_real_e2e.py::test_exe_worker_transcribes_real_video`)
- [ ] If SMTV path changed: live SMTV smoke
      (`tests/smoke/test_smtv_download_e2e.py`)

## Doc updates

- [ ] CHANGELOG.md `[Unreleased]` entry
- [ ] If feature is user-visible: README.md / INSTALL.md updated
- [ ] If feature is build-related: BUILD.md updated
- [ ] If feature is a gap-closer: docs/COMPARISON.md and docs/ROADMAP.md updated

## Notes for the reviewer

<!-- Anything that's not obvious from the diff. Design trade-offs,
unusual approaches, things you considered and rejected. -->
