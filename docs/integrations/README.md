# Integrations

Interoperability with third-party tools. Both integrations below are shipped;
the design notes, implementation briefs and acceptance plans that led to them
are no longer kept in the repository.

## Index

| Integration | Status | Code | Tests |
|---|---|---|---|
| oTranscribe (web app for manual transcription): bidirectional `.otr` converter, Export/Import UI, `Help -> Open oTranscribe` | shipped | [`core/integrations/otranscribe.py`](../../core/integrations/otranscribe.py) | `tests/integrations/test_otranscribe.py` |
| Supreme Master TV (multi-quality download + transcript) | shipped | [`core/integrations/smtv.py`](../../core/integrations/smtv.py) | `tests/integrations/test_smtv.py` |
| machine-translate-docx (sibling translator tool, SMTV docx compatibility) | researched, not scoped | none | none |

## How to add a new integration

1. Put the integration code under `core/integrations/<name>.py` with a module
   docstring that states the public API and the format or page contract it
   relies on.
2. Add tests under `tests/` and a row to the index above.
3. Record the user-visible change in [`docs/CHANGELOG.md`](../CHANGELOG.md).
