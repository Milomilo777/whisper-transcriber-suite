"""The only words an error-message shape may keep (see :mod:`core.diagnostic`).

General English function words plus the technical vocabulary of Python, NumPy, FFmpeg/PyAV, CTranslate2, yt-dlp and
the operating systems' own error texts. Names of people, folders, files, accounts, sites and projects are not here and
must never be added: a word belongs in this list only if it appears in library or operating-system messages.
"""
from __future__ import annotations

_WORDS = """
a an and are as at be been by can cannot could did do does done for from had has have if in into is it its may must
no not of on or out over should so than that the then there these this those to too under up use used using was were
when where which while will with without would
above after again all any before below between both but each either else empty end ended every few first found
good has last less more most much new next none only other same second several since some such third through
true false none null nan inf
abort aborted access accessed accessible accepted add added address after alloc allocate allocated allocating
allocation already ambiguous an argument arguments array arrays assertion attempt attribute audio available
bad base bit bits block blocked bool boolean bound bounds broadcast broken buffer buffers busy byte bytes
cache call callable called cancel cancelled cannot cast chain change channel channels character characters check
checksum chunk class client close closed closing code codec codecs command compatible compile complete completed
compute condition config configuration connect connected connection constant container content context
continue contiguous convert converted copy corrupt corrupted count create created cuda cudnn cublas current
data database dead deadlock decode decoder decoding default deleted denied dependency depth destination detect
detected device devices dictionary dimension dimensions directory disabled disk divide division dll dtype
duplicate duration dynamic
eof element elements empty enable enabled encode encoder encoding encountered end engine enough entry
environment errno error errors exceeded exception exist exists expected expecting extension external
fail failed failure fatal feature features fetch field file files filter finished float float16 float32 float64
floating folder forbidden format found frame frames free function
gb generate generated generation get gpu graph greater
handle handler handles has hash header heap hit hop host http https
identifier illegal incomplete incompatible incorrect index indices inf infinity init initialize initialized
initialization input insufficient int int16 int32 int64 integer interrupted invalid iterable
key keys kind
language languages large last layer lib library limit line list load loaded loading local lock locked log long
lookup loop lower
mapping match matrix max maximum may mb mel memory message method min missing mismatch mismatched mode model
models module more mp3 mp4 multiple must
name named need needed negative network no nonzero normal not null number
object objects offset ok open opened operand operation operations option optional order ordinal os out outside
overflow overrun
packet packets parameter parameters parse parsed parser partial pass permission pipe plugin pointer pool port
position positive postprocessor precision prefix premature preprocess probe process processor protocol
queue quota
raise raised range rate raw read readable reading reason recognized reference refused relative remote remove
removed required reset resolve resource response result retry return returned
sample samples scalar sequence server session set shape shapes shared short signal signed size skipped slice
socket sorted source space speech split stack start started state status step stream streams string strings
structure subprocess success supported symbol syntax system
tensor terminated text thread threads time timed timeout timestamp timestamps token tokens too total trace
traceback track tuple type types
unable unavailable unexpected unicode unknown unpack unsupported unterminated upper url usage user utf
valid value values variable vector version video vocabulary
wait waiting warning wav weights width winerror write writing wrong
zero zip
connection reset aborted refused timed out host unreachable name resolution temporary failure certificate verify
ssl tls handshake proxy redirect status code bad gateway service unavailable too many requests forbidden
gone sign confirm bot login cookies private age restricted geo blocked unavailable extractor sabr nsig player
format requested available
disk full space left device quota exceeded read only file system sharing violation another process using
cuda driver version insufficient runtime kernel image available launch failure library found cannot loaded
cannot allocate bad alloc std
mismatch ctc beam search temperature compression ratio logprob prompt segment segments vad silero onnx diarization
speaker speakers embedding embeddings cluster clusters
""".split()

VOCABULARY: frozenset[str] = frozenset(w for w in _WORDS if w.isalpha() or w.isalnum())
