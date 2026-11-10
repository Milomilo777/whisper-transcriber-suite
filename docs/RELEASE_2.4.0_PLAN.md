# Version 2.4.0 proposal and execution plan

Date: 2026-11-10. Base: v2.3.1 plus the existing Unreleased fixes.
Working branch: `release/2.4.0`. Live handoff: [BOARD.md](BOARD.md).

## Discovery

Read the roadmap, changelog, decisions, comparison, release process, recent
language/timing/download investigations and commits since v2.3.1. The public
issue list contains [Blackwell detection #7](https://github.com/Milomilo777/whisper-transcriber-suite/issues/7)
and [translation review #10](https://github.com/Milomilo777/whisper-transcriber-suite/issues/10).
Neither is a new feature request this week.

Competitor watch covers November 3–10. These are source changes, not claims that
the changes have reached packaged releases. Subtitle Edit improved
[CJK quality reporting](https://github.com/SubtitleEdit/subtitleedit/pull/16708)
and [generated-file feedback](https://github.com/SubtitleEdit/subtitleedit/pull/16676).
Buzz addressed [filename reuse](https://github.com/chidiwilliams/buzz/pull/1703)
and [long-recording alignment memory](https://github.com/chidiwilliams/buzz/pull/1694).
Handy's [vocabulary support](https://github.com/cjpais/Handy/releases/tag/v0.10.0)
is useful context from November 2, outside this week's window. Previous research
already identified saved dictionaries; this is not a newly discovered gap.
No verified Vibe changes were found in the window. No claim of inactivity follows.

| Candidate | User value | Effort | Risk | Decision |
|---|---|---|---|---|
| Named transcription presets | Reuse language, recognition and output choices | Medium | Medium: settings compatibility | Select |
| Editor subtitle quality panel | Locate fast, long or poorly timed cues | Small–medium | Low: advisory only | Select |
| Download bandwidth limit | Keep downloads from consuming the connection | Small | Low: existing yt-dlp option | Select |
| Saved vocabulary profiles | Reuse specialist terminology | Small–medium | Low | Covered by presets |
| CJK display-width metric | Better mixed-width subtitle checks | Small | Medium: metric compatibility | Defer |
| Batch completion summary | Find generated files and failures | Small–medium | Low | Defer: existing result actions need UX audit |
| Filename reuse audit | Avoid matching similarly named media | Small | Low | Follow-up: no reproduced defect |
| Long-file diarization memory audit | Improve reliability for long recordings | Medium–large | Medium | Follow-up; existing fixes remain included |
| Visible language confidence | Help identify uncertain detection | Small–medium | Medium | Defer until current detection fixes settle |

## Chosen scope

Three independent desktop improvements complement the existing reliability work.
Presets shorten repeated setup, quality findings make subtitle review practical,
and bandwidth control improves downloads on shared connections. Defaults keep
existing behavior. Presets use an explicit safe settings list; quality checks do
not rewrite text or timestamps; the limit applies to supported yt-dlp paths.

Each lane has its own branch and worktree, regression tests written before
implementation, a two-round independent critic review, documentation and full
type/test gates. Each feature commit includes its short public changelog entry; integration adds packaging entries.
Real Windows data and GUI exercises are required before declaring features ready.

## Out of scope

- New ASR engines, large model downloads, global dictation or a GUI rewrite.
- Automatic subtitle retiming/reflow or destructive transcript cleanup.
- Arbitrary yt-dlp flags, download scheduling or parallel download workers.
- Paid services, new telemetry behavior, signing certificates or live deployment.
- Tagging, release publication, master pushes or editing published release assets.
- Mac artifact builds without supervised macOS verification.

## Release preparation

After integration and validation: update runtime, project and installer versions,
move Unreleased entries into 2.4.0, prepare local release notes and build the
Windows installer from committed source. Preserve any previous build tree before
the build script replaces it. Record artifact hashes and remaining manual checks.
Stop before tagging or publication; owner approval is required for that step.
