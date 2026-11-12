# Bounded transcript rescue selection

A long series of silent gaps could consume every rescue candidate slot before
a later low-word-count segment was checked. Rescue now checks collapsed segments
before speculative gaps while retaining the limit of 20 speech checks and the
existing decoded-audio budget, piece lengths, speech thresholds and acceptance
rules. Candidates left unchecked at the limit are reported with their time range;
an unchecked gap is not described as confirmed silence.

Selection priority is separate from replacement order. Selected spans are sorted
by their original transcript indexes and replaced from the end, preserving the
original segments outside each replacement. Warning ranges are reported in time
order. Callback-driven tests cover silent-prefix starvation, exhausted limits and
mixed gap/segment splicing; they do not establish recognition quality on new media.
