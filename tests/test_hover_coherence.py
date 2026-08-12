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


def test_only_one_thing_is_highlighted_at_the_nation_level():
    """Hovering anywhere in a state at the zoomed-out level highlights the STATE and nothing
    else. Marking the county under the cursor as well draws a second, smaller highlight inside
    the first — two things apparently selected, and the inner one promising a county selection
    the click will not make. Below the nation level the county IS the click target and marks
    normally, so the class is conditional rather than removed.
    """
    for f in COUNTY_SHADED:
        s = _src(f)
        assert 'classed("hovered", level !== 0)' in s, (
            f"{f}: the county mark must be suppressed at the nation level")
        # Scoped to the COUNTY hover. PRF's hoverGrid marks unconditionally and should:
        # grid cells are only ever drawn at the deepest level, so there is no level at which
        # marking one is wrong. Asserting "no unconditional mark anywhere" would forbid that.
        county_hover = s.split("function hover(ev, d)")[1][:800]
        assert 'classed("hovered", true)' not in county_hover, (
            f"{f}: the county mark must be conditional on level")


def test_a_hover_handler_that_uses_this_is_called_with_this():
    """PRF registered `hover(ev, d)` where row crop registered `hover.call(this, ev, d)`.

    Called plainly, `this` inside the handler is not the path, so d3.select(this) selects
    nothing — which meant PRF's `.county.hovered` CSS rule had never applied since the day it
    was written. Nobody noticed because the visible county highlight comes from the .hoverline
    outline added later, so the dead rule was masked by a working feature.

    The rule: a handler whose body touches d3.select(this) must be invoked with .call(this).
    webmap is exempt and checked separately — its hover takes a plain region object and marks
    by data match, never touching `this`.
    """
    for f in ("src/prfpage.py", "src/rowcroppage.py", "src/drppage.py"):
        s = _src(f)
        for m in re.finditer(r'\.on\("mousemove", function \(ev[^)]*\) \{ (\w+)\(', s):
            raise AssertionError(
                f"{f}: hover handler {m.group(1)}(...) is called without .call(this); "
                f"d3.select(this) inside it will select nothing")
        assert ".call(this," in s, f"{f}: expected at least one bound hover handler"

    web = _src("src/webmap.py")
    assert "d3.select(this)" not in web, (
        "webmap's hover marks by data match and must not start relying on `this`")
