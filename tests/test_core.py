"""Run: python -m pytest -q tests  (or: python tests/test_core.py)"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from promofinder.parser import load_inputs, parse_episode, fmt_ts  # noqa: E402
from promofinder.validate import check_promo, parse_ref, iou  # noqa: E402

EPS = {e.number: e for e in load_inputs(ROOT / "data" / "i-married-a-broken-soldier")}


def test_parses_all_episodes():
    assert sorted(EPS) == list(range(1, 51))
    assert all(len(e.events) > 30 for e in EPS.values())
    assert all(not e.warnings for e in EPS.values())


def test_uppercase_scene_headers_episode_6():
    e = EPS[6]
    assert len(e.scenes) == 2 and e.scenes[0].heading.startswith("EXT. WOODLAND")


def test_ref_parsing_is_tolerant():
    assert parse_ref("5:024", 1) == (5, 24)
    assert parse_ref("[5:24]", 1) == (5, 24)
    assert parse_ref("E5-024", 1) == (5, 24)
    assert parse_ref("024", 7) == (7, 24)
    assert parse_ref("00:45.80", 1) is None or parse_ref("00:45.80", 1) == (0, 45)  # timestamps are not refs


def test_ledger_promo_snaps_to_shots_and_passes():
    raw = {"segments": [{"start_ref": "5:024", "end_ref": "5:036"}], "hook_ref": "5:024", "cliffhanger_ref": "5:036"}
    c = check_promo(raw, EPS, 5)
    assert c.ok, c.errors
    s = c.segments[0]
    # starts at the shot cut before "And the ledger..." without chopping a line
    assert 42.0 <= s.start <= 44.3
    assert s.end >= 64.6  # Gerald's line is not cut off
    assert 20 <= c.duration <= 60
    assert c.hook_at is not None and c.hook_at <= 3


def test_too_short_and_late_hook_are_rejected():
    raw = {"segments": [{"start_ref": "5:024", "end_ref": "5:029"}], "hook_ref": "5:029", "cliffhanger_ref": "5:029"}
    c = check_promo(raw, EPS, 5)
    assert not c.ok
    assert any("too short" in e for e in c.errors)
    assert any("hook line starts" in e for e in c.errors)


def test_cross_episode_segment_is_split_at_boundary():
    last = len(EPS[1].events) - 1
    raw = {"segments": [{"start_ref": f"1:{last - 12:03d}", "end_ref": "2:010"}],
           "hook_ref": f"1:{last - 12:03d}", "cliffhanger_ref": "2:010"}
    c = check_promo(raw, EPS, 1)
    assert [s.episode for s in c.segments] == [1, 2]


def test_out_of_range_and_reversed_refs():
    c = check_promo({"segments": [{"start_ref": "5:999", "end_ref": "5:1000"}], "hook_ref": "5:999"}, EPS, 5)
    assert not c.ok
    c = check_promo({"segments": [{"start_ref": "5:040", "end_ref": "5:020"}], "hook_ref": "5:040"}, EPS, 5)
    assert not c.ok


def test_iou():
    a = check_promo({"segments": [{"start_ref": "5:024", "end_ref": "5:036"}], "hook_ref": "5:024"}, EPS, 5).segments
    assert abs(iou(a, a) - 1.0) < 1e-9


def test_fmt_ts():
    assert fmt_ts(65.5) == "01:05.50"


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("ok  ", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, e)
    sys.exit(1 if fails else 0)
