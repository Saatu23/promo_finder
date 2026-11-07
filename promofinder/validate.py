"""Turn the model's line-ID picks into exact, rule-checked cut points. Pure code.

Why: models are good at judging drama and bad at arithmetic on timestamps. So the
model only names line IDs; this module owns every number in the output.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .parser import Episode, Event, fmt_ts

MIN_LEN, MAX_LEN, HOOK_WINDOW = 20.0, 60.0, 3.0
SNAP_BACK, SNAP_FWD = 1.5, 1.5


@dataclass
class Segment:
    episode: int
    start: float
    end: float
    start_ref: str
    end_ref: str

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 2)

    def to_dict(self) -> dict:
        return {"episode": self.episode, "start": fmt_ts(self.start), "end": fmt_ts(self.end),
                "start_s": round(self.start, 2), "end_s": round(self.end, 2), "duration_s": self.duration,
                "start_ref": self.start_ref, "end_ref": self.end_ref}


@dataclass
class Checked:
    segments: list[Segment]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    hook_at: float | None = None          # seconds into clip where hook line starts
    cliff_gap: float | None = None        # seconds between cliffhanger line end and clip end

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def duration(self) -> float:
        return round(sum(s.duration for s in self.segments), 2)


REF_RE = re.compile(r"\[?\s*(?:E|EP)?\s*(\d+)\s*[:.\-]\s*(\d+)\s*\]?", re.I)


def parse_ref(ref, default_ep: int) -> tuple[int, int] | None:
    if ref is None:
        return None
    s = str(ref).strip()
    m = REF_RE.fullmatch(s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.fullmatch(r"\[?(\d+)\]?", s)
    if m:
        return default_ep, int(m.group(1))
    return None


def _straddles(dialogue: list[Event], t: float) -> bool:
    """True if cutting at t would chop a spoken line."""
    return any(d.start < t - 0.05 and d.end > t + 0.15 for d in dialogue)


def snap_start(ep: Episode, t0: float) -> float:
    dialogue = ep.dialogue
    cuts = sorted({round(s.start, 3) for s in ep.shots})
    options = [c for c in cuts if t0 - SNAP_BACK <= c <= t0 + 0.05 and not _straddles(dialogue, c)]
    if options:
        return max(options)
    return t0


def snap_end(ep: Episode, t1: float) -> float:
    dialogue = ep.dialogue
    cuts = sorted({round(s.end, 3) for s in ep.shots} | {round(s.start, 3) for s in ep.shots})
    for c in cuts:
        if c < t1 - 0.05 or c > t1 + SNAP_FWD:
            continue
        # never let the next spoken line (often the answer) leak into the clip
        if any(t1 + 0.05 < d.start < c - 0.1 for d in dialogue):
            continue
        if _straddles(dialogue, c):
            continue
        return max(c, t1)
    nxt = [d.start for d in dialogue if d.start > t1 + 0.05]
    return min(t1 + 0.3, nxt[0] - 0.05) if nxt else min(t1 + 0.3, ep.duration)


def build_segments(raw_segments: list[dict], eps: dict[int, Episode], default_ep: int) -> tuple[list[Segment], list[str]]:
    errors: list[str] = []
    segs: list[Segment] = []
    for i, rs in enumerate(raw_segments or []):
        a = parse_ref(rs.get("start_ref"), default_ep)
        b = parse_ref(rs.get("end_ref"), default_ep)
        if not a or not b:
            errors.append(f"segment {i + 1}: unreadable refs {rs.get('start_ref')!r}..{rs.get('end_ref')!r}")
            continue
        (ea, ia), (eb, ib) = a, b
        if ea not in eps or eb not in eps:
            errors.append(f"segment {i + 1}: episode {ea if ea not in eps else eb} not loaded")
            continue
        if ia >= len(eps[ea].events) or ib >= len(eps[eb].events):
            errors.append(f"segment {i + 1}: line ID out of range ({ea}:{ia:03d} / {eb}:{ib:03d})")
            continue
        if (ea, ia) > (eb, ib):
            errors.append(f"segment {i + 1}: start {ea}:{ia:03d} is after end {eb}:{ib:03d}")
            continue
        # a segment that runs across an episode boundary is split at the boundary
        pieces = [(ea, ia, ib)] if ea == eb else [(ea, ia, len(eps[ea].events) - 1)] + \
            [(e, 0, len(eps[e].events) - 1) for e in range(ea + 1, eb) if e in eps] + [(eb, 0, ib)]
        for e, s_i, e_i in pieces:
            ep = eps[e]
            evs = ep.events[s_i:e_i + 1]
            t0 = ep.events[s_i].start
            # end at the end of the chosen last line (dialogue/action), not at a long camera shot that runs on
            t1 = ep.events[e_i].end
            spoken_inside = [d.end for d in evs if d.kind == "dialogue"]
            if spoken_inside:
                t1 = max(t1, max(spoken_inside))
            segs.append(Segment(e, snap_start(ep, t0), snap_end(ep, t1), f"{e}:{s_i:03d}", f"{e}:{e_i:03d}"))
    return segs, errors


def check_promo(raw: dict, eps: dict[int, Episode], default_ep: int) -> Checked:
    segs, errors = build_segments(raw.get("segments", []), eps, default_ep)
    c = Checked(segments=segs, errors=errors)
    if not segs:
        c.errors.append("no usable segments")
        return c
    # order / overlap
    for x, y in zip(segs, segs[1:]):
        if (y.episode, y.start) < (x.episode, x.end - 0.05) and not (y.episode > x.episode):
            c.errors.append(f"segments overlap or are out of story order ({x.start_ref}..{x.end_ref} then {y.start_ref})")
    if len(segs) > 4:
        c.errors.append(f"{len(segs)} segments; keep it to at most 3 moments")
    dur = c.duration
    if dur < MIN_LEN - 0.25:
        c.errors.append(f"too short: {dur:.1f}s (min {MIN_LEN:.0f}s)")
    if dur > MAX_LEN + 0.25:
        c.errors.append(f"too long: {dur:.1f}s (max {MAX_LEN:.0f}s)")
    # hook must start inside the first 3 seconds of the clip
    first = segs[0]
    hk = parse_ref(raw.get("hook_ref"), default_ep)
    if hk and hk[0] in eps and hk[1] < len(eps[hk[0]].events):
        h = eps[hk[0]].events[hk[1]]
        if h.episode != first.episode or h.start < first.start - 0.05 or h.start > first.end:
            c.errors.append(f"hook line {hk[0]}:{hk[1]:03d} is not inside the first segment")
        else:
            c.hook_at = round(h.start - first.start, 2)
            if c.hook_at > HOOK_WINDOW:
                c.errors.append(f"hook line starts {c.hook_at:.1f}s into the clip (must be within {HOOK_WINDOW:.0f}s)")
    else:
        c.errors.append(f"hook_ref {raw.get('hook_ref')!r} is not a valid line ID")
    # what actually plays in the first 3 seconds?
    ep0 = eps[first.episode]
    opening = [e for e in ep0.events if e.start < first.start + HOOK_WINDOW and e.end > first.start
               and e.start >= first.start - 0.05]
    if not any(e.kind in ("dialogue", "action") for e in opening):
        c.warnings.append("first 3s contain only camera/sound description - hook may be visual-only")
    # cliffhanger should be the last thing in the clip
    last = segs[-1]
    ck = parse_ref(raw.get("cliffhanger_ref"), default_ep)
    if ck and ck[0] in eps and ck[1] < len(eps[ck[0]].events):
        cl = eps[ck[0]].events[ck[1]]
        if cl.episode != last.episode or cl.end < last.start or cl.start > last.end:
            c.errors.append(f"cliffhanger line {ck[0]}:{ck[1]:03d} is not inside the last segment")
        else:
            c.cliff_gap = round(last.end - cl.end, 2)
            if c.cliff_gap > 4.0:
                c.warnings.append(f"clip runs {c.cliff_gap:.1f}s past the cliffhanger line - may dilute the cut")
    else:
        c.warnings.append(f"cliffhanger_ref {raw.get('cliffhanger_ref')!r} not a valid line ID")
    # does the very next spoken line resolve it? (flag for the judge / human)
    ep_l = eps[last.episode]
    nxt = [d for d in ep_l.dialogue if d.start >= last.end - 0.05]
    if nxt and nxt[0].start - last.end < 1.0:
        c.warnings.append(f"next line follows within 1s of the cut: {nxt[0].speaker}: {nxt[0].text[:60]}")
    return c


def clip_events(segs: list[Segment], eps: dict[int, Episode]) -> list[tuple[float, Event]]:
    """Events that play in the clip, with time relative to clip start."""
    out, offset = [], 0.0
    for s in segs:
        ep = eps[s.episode]
        for e in ep.events:
            if e.start >= s.start - 0.05 and e.start < s.end - 0.05:
                out.append((round(offset + e.start - s.start, 2), e))
        offset += s.duration
    return out


def render_clip(segs: list[Segment], eps: dict[int, Episode], until: float | None = None,
                include_camera: bool = True) -> str:
    lines, offset = [], 0.0
    for k, s in enumerate(segs):
        if k:
            lines.append("--- [CUT TO A LATER MOMENT] ---")
        ep = eps[s.episode]
        for e in ep.events:
            if not (e.start >= s.start - 0.05 and e.start < s.end - 0.05):
                continue
            rel = offset + e.start - s.start
            if until is not None and rel >= until:
                break
            if e.kind == "camera" and not include_camera:
                continue
            tag = f"{int(rel // 60)}:{rel % 60:04.1f}"
            if e.kind == "dialogue":
                lines.append(f"{tag} {e.speaker}{' (' + e.delivery + ')' if e.delivery else ''}: {e.text}")
            else:
                lines.append(f"{tag} [{e.kind.upper()}] {e.text}")
        offset += s.duration
    return "\n".join(lines)


def overlap_seconds(a: list[Segment], b: list[Segment]) -> float:
    tot = 0.0
    for x in a:
        for y in b:
            if x.episode == y.episode:
                tot += max(0.0, min(x.end, y.end) - max(x.start, y.start))
    return tot


def iou(a: list[Segment], b: list[Segment]) -> float:
    inter = overlap_seconds(a, b)
    da = sum(s.end - s.start for s in a)
    db = sum(s.end - s.start for s in b)
    union = da + db - inter
    return inter / union if union > 0 else 0.0
