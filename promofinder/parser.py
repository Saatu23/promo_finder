"""Parse microdrama screenplay .txt files into structured, timestamped events.

Pure code, no AI. Every timestamp the tool ever outputs comes from here, so the
model can never invent one: prompts show the model numbered lines, the model
answers with line IDs, and code maps IDs back to times.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

TS = r"(\d{1,2}):(\d{2}(?:\.\d+)?)"
EVENT_HEADER = re.compile(r"^\*\*(?P<label>.+?):\*\*\s*$")
EVENT_TIME = re.compile(rf"^Start:\s*\({TS}\)\s*\|\s*End:\s*\({TS}\)\s*$", re.I)
SCENE_NO = re.compile(r"^SCENE\s+(\d+)\s*$", re.I)
SCENE_FIELD = re.compile(r"^Scene (heading|start|end):\s*(.*)$", re.I)
HEADER_FIELD = re.compile(r"^(EPISODE NUMBER|EPISODE LOGLINE|CONTINUITY NOTES):\s*(.*)$", re.I)

NON_DIALOGUE = {"CAMERA": "camera", "ACTION": "action", "SOUND FX": "sfx", "SFX": "sfx", "MUSIC": "sfx"}


def to_seconds(m: str, s: str) -> float:
    return round(int(m) * 60 + float(s), 3)


def fmt_ts(t: float) -> str:
    """Seconds -> MM:SS.ss (same style as the screenplays)."""
    t = max(0.0, t)
    m = int(t // 60)
    return f"{m:02d}:{t - m * 60:05.2f}"


@dataclass
class Event:
    idx: int                 # 0-based index within episode (stable line ID)
    episode: int
    scene: int
    kind: str                # camera | action | sfx | dialogue
    start: float
    end: float
    text: str
    speaker: str = ""        # dialogue only, raw label without parenthetical
    delivery: str = ""       # e.g. "Cold, Commanding"

    @property
    def ref(self) -> str:
        return f"{self.episode}:{self.idx:03d}"

    def render(self, with_ep: bool = False) -> str:
        """One numbered line as shown to the model."""
        rid = self.ref if with_ep else f"{self.idx:03d}"
        span = f"{fmt_ts(self.start)}-{fmt_ts(self.end)}"
        if self.kind == "dialogue":
            who = self.speaker + (f" ({self.delivery})" if self.delivery else "")
            return f"[{rid}] {span} {who}: {self.text}"
        return f"[{rid}] {span} {self.kind.upper()}: {self.text}"


@dataclass
class Scene:
    number: int
    heading: str = ""
    start: float | None = None
    end: float | None = None


@dataclass
class Episode:
    number: int
    logline: str
    continuity: str
    source: str
    scenes: list[Scene] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        ends = [e.end for e in self.events] + [s.end for s in self.scenes if s.end is not None]
        return max(ends) if ends else 0.0

    @property
    def shots(self) -> list[Event]:
        return [e for e in self.events if e.kind == "camera"]

    @property
    def dialogue(self) -> list[Event]:
        return [e for e in self.events if e.kind == "dialogue"]

    def render(self, with_ep: bool = False, kinds: set[str] | None = None,
               start: float | None = None, end: float | None = None) -> str:
        out = []
        for e in self.events:
            if kinds and e.kind not in kinds:
                continue
            if start is not None and e.end <= start:
                continue
            if end is not None and e.start >= end:
                continue
            out.append(e.render(with_ep))
        return "\n".join(out)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration"] = self.duration
        return d


def parse_episode(text: str, source: str = "") -> Episode:
    lines = [l.rstrip() for l in text.splitlines()]
    header: dict[str, str] = {}
    warnings: list[str] = []
    scenes: list[Scene] = []
    events: list[Event] = []
    cur_scene: Scene | None = None
    pending: dict | None = None  # header seen, waiting for time + text
    in_script = False

    def flush():
        nonlocal pending
        if pending is None:
            return
        if pending.get("start") is None:
            warnings.append(f"line {pending['line']}: event '{pending['label']}' has no timestamps; skipped")
        elif not pending["text"]:
            warnings.append(f"line {pending['line']}: event '{pending['label']}' has no text; skipped")
        else:
            label = pending["label"]
            m = re.match(r"^(.*?)\s*\((.*)\)\s*$", label)
            base, paren = (m.group(1), m.group(2)) if m else (label, "")
            base_u = base.strip().upper()
            kind = NON_DIALOGUE.get(base_u, "dialogue")
            text_ = " ".join(pending["text"]).strip()
            if kind == "dialogue":
                text_ = text_.strip()
            s, e = pending["start"], pending["end"]
            if e < s:
                warnings.append(f"line {pending['line']}: end before start ({s}>{e}); swapped")
                s, e = e, s
            events.append(Event(idx=len(events), episode=0, scene=cur_scene.number if cur_scene else 1,
                                kind=kind, start=s, end=e, text=text_,
                                speaker=base.strip() if kind == "dialogue" else "",
                                delivery=paren.strip() if kind == "dialogue" else ""))
        pending = None

    for i, raw in enumerate(lines, 1):
        line = raw.strip()
        if not in_script:
            m = HEADER_FIELD.match(line)
            if m:
                header[m.group(1).upper()] = m.group(2).strip()
                continue
            if line.upper().startswith("--- SCRIPT START"):
                in_script = True
            continue
        if line.upper().startswith("--- SCRIPT END"):
            flush()
            break
        if not line:
            continue
        m = SCENE_NO.match(line)
        if m:
            flush()
            cur_scene = Scene(number=int(m.group(1)))
            scenes.append(cur_scene)
            continue
        m = SCENE_FIELD.match(line)
        if m and cur_scene is not None:
            k, v = m.group(1).lower(), m.group(2).strip()
            if k == "heading":
                cur_scene.heading = v
            else:
                tm = re.match(TS, v)
                if tm:
                    setattr(cur_scene, k, to_seconds(*tm.groups()))
                else:
                    warnings.append(f"line {i}: bad scene {k} '{v}'")
            continue
        if re.match(r"^actions and dialogue:?$", line, re.I):
            continue
        m = EVENT_HEADER.match(line)
        if m:
            flush()
            pending = {"label": m.group("label").strip(), "start": None, "end": None, "text": [], "line": i}
            continue
        m = EVENT_TIME.match(line)
        if m and pending is not None and pending["start"] is None:
            pending["start"] = to_seconds(m.group(1), m.group(2))
            pending["end"] = to_seconds(m.group(3), m.group(4))
            continue
        if pending is not None and pending["start"] is not None:
            pending["text"].append(line.strip('"').strip() if pending["label"].upper().split(" (")[0] not in NON_DIALOGUE else line)
            continue
        warnings.append(f"line {i}: unrecognised line '{line[:60]}'")
    else:
        flush()
        if in_script:
            warnings.append("missing '--- SCRIPT END ---'")

    ep_field = header.get("EPISODE NUMBER", "")
    m = re.search(r"(\d+)", ep_field)
    if m:
        number = int(m.group(1))
    else:
        m = re.search(r"episode[-_ ]?(\d+)", source, re.I)
        number = int(m.group(1)) if m else 0
        warnings.append(f"episode number not in header; took {number} from filename")

    for e in events:
        e.episode = number
    # dialogue text was split per line; rejoin quoted dialogue cleanly
    for e in events:
        if e.kind == "dialogue":
            e.text = '"' + e.text.strip('"').strip() + '"'

    if not events:
        warnings.append("no events parsed")
    ep = Episode(number=number, logline=header.get("EPISODE LOGLINE", ""),
                 continuity=header.get("CONTINUITY NOTES", ""), source=source,
                 scenes=scenes, events=events, warnings=warnings)
    return ep


def load_inputs(path: str | Path | None = None, files: list[tuple[str, bytes]] | None = None) -> list[Episode]:
    """Load episodes from a folder, a single .txt, a .zip, or in-memory uploads."""
    blobs: list[tuple[str, bytes]] = list(files or [])
    if path is not None:
        p = Path(path)
        if p.is_dir():
            blobs += [(str(f.name), f.read_bytes()) for f in sorted(p.rglob("*.txt"))]
        elif p.suffix.lower() == ".zip":
            blobs.append((p.name, p.read_bytes()))
        else:
            blobs.append((p.name, p.read_bytes()))
    expanded: list[tuple[str, bytes]] = []
    for name, data in blobs:
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    base = info.filename.rsplit("/", 1)[-1]
                    if base.lower().endswith(".txt") and not base.startswith("._") and "__MACOSX" not in info.filename:
                        expanded.append((base, z.read(info)))
        elif name.lower().endswith(".txt"):
            expanded.append((name.rsplit("/", 1)[-1], data))
    episodes = [parse_episode(d.decode("utf-8-sig", errors="replace"), n) for n, d in expanded]
    episodes = [e for e in episodes if e.events]
    episodes.sort(key=lambda e: e.number)
    seen = set()
    for e in episodes:
        if e.number in seen:
            e.warnings.append(f"duplicate episode number {e.number}")
        seen.add(e.number)
    return episodes
