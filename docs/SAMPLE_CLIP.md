# "Try it now" sample clip

`assets/sample_clip.mp3` is a spoken clip of about 18 seconds that a new user can transcribe with
one click ("Finish and try it now" in the quick start window, or "Try it now (sample clip)" on the
Transcribe tab) before they have a file of their own. The app copies it to its user data folder
(`samples/`) first, because the install folder can be read-only and a transcript is written next
to its source file. Code: `core/sample_clip.py`, `App.try_sample_clip`.

## Source and licence

| | |
|---|---|
| Work | *A Color Notation*, Albert Henry Munsell, part 1 chapter 1 ("Color Names"), a LibriVox recording |
| Speaker | Availle (LibriVox volunteer reader), recorded March 2017 |
| Source file | <https://commons.wikimedia.org/wiki/File:Albert_Henry_Munsell_-_A_Color_Notation_(LibriVox)_01.mp3> |
| Text source | <https://archive.org/details/acolornotationam26054gut> |
| Licence | CC0 1.0 (public domain dedication), as stated on the Wikimedia Commons page; LibriVox recordings are public domain |

The clip is the excerpt from 0:21.0 to 0:39.5 of that file (the letter beginning "Writing from
Samoa to Sydney Colvin in London"), cut and re-encoded with ffmpeg as 16 kHz mono MP3 at 48 kbit/s
with a short fade at each end (about 110 KB). Nothing else was changed.

To rebuild it from the source file:

```
ffmpeg -ss 21.0 -t 18.5 -i <source>.mp3 -ac 1 -ar 16000 -af "afade=t=in:d=0.03,afade=t=out:st=18.2:d=0.3" -c:a libmp3lame -b:a 48k assets/sample_clip.mp3
```

## Shipping

`assets/` is a data directory in all three PyInstaller specs, so the clip is bundled with each of
them; `installer.iss` and `installer_embed.iss` list it by name next to the icon files, because
the icons and the clip are read from the install folder. `tests/core/test_sample_clip.py` checks
every list.
