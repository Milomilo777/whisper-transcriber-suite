// Transcript formats for /try/: Whisper chunks -> cues -> SRT / VTT. Pure functions (tested with Node).

export function stamp(sec, sep) {
  const ms = Math.max(0, Math.round((sec || 0) * 1000));
  const h = Math.floor(ms / 3600000), m = Math.floor(ms / 60000) % 60, s = Math.floor(ms / 1000) % 60;
  const pad = (n, w = 2) => String(n).padStart(w, '0');
  return `${pad(h)}:${pad(m)}:${pad(s)}${sep}${pad(ms % 1000, 3)}`;
}

// chunks: [{timestamp: [start, end], text}] from the pipeline. The last chunk's end can be null: use the next
// start, the audio length, or start + 2 s, and no cue ends after the audio. Empty texts are dropped; every cue
// lasts at least 0.2 s.
export function cues(chunks, duration) {
  return chunks.map((c, i) => {
    const [a, b] = c.timestamp || [];
    const next = chunks[i + 1] && chunks[i + 1].timestamp ? chunks[i + 1].timestamp[0] : null;
    const start = a || 0;
    let end = b ?? next ?? (duration || start + 2);
    if (duration && end > duration) end = duration;  // never past the end of the audio
    return { start, end: Math.max(end, start + 0.2), text: (c.text || '').trim() };
  }).filter((c) => c.text);
}

// Whisper's segment timestamps in the browser are coarse (one cue can span 30 s). Split a long cue at
// sentence ends, then commas, then spaces, into pieces of at most maxChars, and share its time by length.
export function splitLong(list, maxChars = 84) {
  const out = [];
  for (const c of list) {
    if (c.text.length <= maxChars) { out.push(c); continue; }
    const pieces = [];
    let rest = c.text;
    while (rest.length > maxChars) {
      const head = rest.slice(0, maxChars + 1);
      let cut = -1;
      for (const re of [/[.!?。！？]\s/g, /[,;:،，、]\s/g, /\s/g]) {
        let m;
        while ((m = re.exec(head)) !== null) cut = m.index + m[0].length;
        if (cut > maxChars / 3) break;
        cut = -1;
      }
      if (cut <= 0) cut = maxChars;  // one long word (or CJK text without spaces): hard cut
      pieces.push(rest.slice(0, cut).trim());
      rest = rest.slice(cut).trim();
    }
    if (rest) pieces.push(rest);
    const total = pieces.reduce((n, p) => n + p.length, 0);
    let t = c.start;
    pieces.forEach((p, i) => {
      const end = i === pieces.length - 1 ? c.end : t + (c.end - c.start) * (p.length / total);
      out.push({ start: t, end, text: p });
      t = end;
    });
  }
  return out;
}

export function toSrt(list) {
  return list.map((c, i) => `${i + 1}\n${stamp(c.start, ',')} --> ${stamp(c.end, ',')}\n${c.text}\n`).join('\n');
}

export function toVtt(list) {
  return 'WEBVTT\n\n' + list.map((c) => `${stamp(c.start, '.')} --> ${stamp(c.end, '.')}\n${c.text}\n`).join('\n');
}
