"""The hover outline and the tooltip must describe the SAME THING.

This is one bug with one shape, and it was introduced deliberately: the outline was changed to
follow the CLICK target (a click at the nation level zooms to a state), while the tooltip was
left on the county under the cursor. The result was a highlighted state next to a box of county
numbers, with nothing telling the reader which the figure belonged to.

The maps differ in how they avoid it and both are correct:

  * DRP and the availability map draw actual STATE shapes at the nation level, so the datum
    under the cursor already is the state. Nothing to reconcile.
  * PRF and row crop shade by COUNTY at every level, so at the nation level they outline the
    state and must roll the counties up to describe it.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
COUNTY_SHADED = ("src/prfpage.py", "src/rowcroppage.py")
STATE_SHAPED = ("src/drppage.py", "src/webmap.py")


def _src(name):
    return (ROOT / name).read_text()


def test_county_shaded_maps_describe_the_state_at_the_nation_level():
    """If the outline is the state, the box has to be about the state."""
    for f in COUNTY_SHADED:
        s = _src(f)
        assert "showHover(level === 0 ? (stateById" in s, f"{f}: outline should be the state"
        assert re.search(r"function stateTip", s), f"{f}: needs a state-level tooltip"
        assert "level === 0" in s.split("tip.innerHTML")[1][:200], (
            f"{f}: the tooltip must branch on level, or it still describes a county")


def test_state_shaped_maps_need_no_rollup():
    """DRP and the availability map draw state shapes at the nation level, so the thing under
    the cursor IS the state. Adding a rollup there would be inventing a problem."""
    for f in STATE_SHAPED:
        s = _src(f)
        assert 'attr("class", "state")' in s, f"{f} should draw state shapes"
        assert "function stateTip" not in s, f"{f} does not need a state rollup"


def test_a_state_figure_is_never_a_sum_of_rates():
    """Summing per-acre or per-dollar figures across counties produces a number with no
    meaning, and an unweighted mean is worse — it looks like an answer. Both maps show a RANGE
    for those, and row crop sums only the three metrics that are genuinely dollar totals.
    """
    rc = _src("src/rowcroppage.py")
    m = re.search(r"var SUMMABLE = \{([^}]*)\}", rc)
    assert m, "row crop must declare which metrics may be summed"
    summable = set(re.findall(r"(\w+):", m.group(1)))
    assert summable == {"total", "adjtotal", "commtot"}, summable
    for rate in ("acre", "adjacre", "prodac", "ret", "miss", "commac", "pen"):
        assert rate not in summable, f"{rate} is a rate and must not be summed"

    prf = _src("src/prfpage.py")
    # strip JS comments first: the note explaining WHY PRF has no SUMMABLE list legitimately
    # names it, and a bare substring check flags its own documentation.
    prf_code = re.sub(r"//[^\n]*", "", prf)
    assert "SUMMABLE" not in prf_code, (
        "no PRF metric sums across counties — CBV is per acre, win rate is a share, and the "
        "returns are per $1 or per acre")
    assert "across counties" in prf


def test_the_rollup_says_it_is_a_range_not_an_average():
    """A reader seeing two numbers needs to know they are the extremes, not a confidence
    interval or a mean plus error."""
    for f in COUNTY_SHADED:
        s = _src(f)
        assert "a range, not an average" in s, f"{f} must say what the two numbers are"
        assert "weights" in s, f"{f} should say WHY a mean is not offered"
