# Resume older checkpoints with out-of-audio timing

An older failure path could save a rejected decoder cue and a cursor beyond the
media end. A later retry then sliced from that invalid cursor or rejected the
same saved cue forever. New streaming checkpoints already validate before append;
this change handles files written by the earlier path.

With a known verified audio extent, resume validates the saved cue/word intervals
before slicing. It durably preserves the complete raw segment list, including
all entries after the first rejection, then uses only the valid prefix. A
recovered checkpoint is partial and must pass decoder compatibility again. It
continues from the greatest valid prefix end, without changing the rejected
text's timestamps. An empty prefix, no remaining audio or unsupported decoder
keeps the original checkpoint aside and requests a fresh run. Recovery-storage
failure aborts before replacing the checkpoint or writing outputs.

Unknown extents do not authorize repair. This does not classify native padding
hallucinations, drain an unconsumed decoder iterator, or repair model-generated
EOF clocks. Those remain separate work. Existing completion/post-processing and
output-persistence paths are unchanged after a successfully decoded tail.

The Fable EOF review's legacy-poisoning claim was reproduced with seven failing
cases and two storage-failure controls. Tests use a real synthetic 600-second
PCM file, actual checkpoint and output writers, and a stub tail decoder. Sixty-four
bounded generated cases check longest-prefix selection and preservation of raw
fields, order and input objects. These are recovery tests, not GPU quality proof.

Review reproduced six malformed saved-word failures. Non-mapping word entries
now follow the same raw-preservation and prefix-recovery path.
