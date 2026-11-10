# Subtitle quality panel

Open a saved transcript in the transcript editor, then choose **Subtitle Quality**.
The panel checks every cue, including cues hidden by the transcript search. It lists
cue numbers, severity, and a plain description of each finding. Select a finding to
reveal that exact cue in the transcript and seek the embedded player to its start
when media is available. The detail text includes the start time in milliseconds.
Keyboard selection in the findings list works as well.

The report refreshes after timestamp edits, Find and Replace, and filler removal.
Checks never modify text or timings, write files, or prevent saving. An error means
a structural issue to inspect, not permission to discard a cue. Warnings are
advisory; intentional repetitions, simultaneous speakers, and fast dialogue can be valid.

The **Reading profile** defaults to the transcript language supplied by its queue
entry. Standalone transcript JSON contains no language metadata, so an unknown
language uses the general profile. Choose General, Chinese, Japanese, Korean, or
Cantonese explicitly when needed. The panel displays its current limits:

- General: 20 visible characters/second, 42 characters/line.
- Chinese, Japanese, Korean, Cantonese: 9 characters/second, 16 characters/line.
- All profiles: two lines, duration 0.833–7 seconds, minimum gap 0.083 seconds.

These are the existing engine's advisory defaults, not certification against any
broadcaster's guide. Counts use visible Unicode characters, not rendered pixel
width. The report also checks empty text, invalid or non-positive timing,
out-of-order cues, overlaps, and adjacent repeated text. It reports current editor
cue boundaries rather than predicting every export writer's rewrapping.
