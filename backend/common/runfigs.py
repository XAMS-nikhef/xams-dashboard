"""Figures of the run page (design 2026-11-04): one question per figure, a reference run in the same panel.

This run as points (with sqrt(n) errors), the reference run as an open grey step histogram scaled to the same number
of selected events; colour maps without a reference. Shared light style (plotstyle.py, a copy of xams-sim's).

    select(e)                       the event selection of every figure: now only S1 and S2 present; cut C goes here
    FIGURES[kind]                   [(name, title, function)] per run kind: "event" (every run), "source", "led"
    make(name, e, ref, info)        a matplotlib Figure (e, ref: numpy record arrays; ref may be None)

Units of event_info: times and widths in ns, positions in mm (r is clipped at the TPC wall, 31 mm), areas in PE,
energy in keV.
"""
from __future__ import annotations

import numpy as np

from . import plotstyle

C = plotstyle.C
EVENT_FIELDS = ["time", "s1_area", "s2_area", "cs1", "cs2", "energy", "drift_time", "s2_range_50p_area", "s2_x", "s2_y"]
LED_FIELDS = ["channel", "area"]
VERSION = 4                                          # part of the cached file names: raise it when a figure changes
TPC_R_MM = 31.0                                      # field cage inner radius (xams2026 geometry); s2_x / s2_y are clipped there


# ------------------------------------------------------------------------------------------------ selection
def select(e) -> np.ndarray:
    """The events every figure uses. Now: an S1 and an S2 (no cuts yet). Cut C (odd events) is added here later
    (SR2026.3/lib/oddcut.py), so the figures themselves do not change."""
    ok = np.ones(len(e), bool)
    for f in ("s1_area", "s2_area"):
        if f in e.dtype.names:
            ok &= np.isfinite(e[f]) & (e[f] > 0)
    return ok


# ------------------------------------------------------------------------------------------------ helpers
def _fig(ncols=1, w=6.4, h=4.0):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plotstyle.apply()
    fig, axs = plt.subplots(1, ncols, figsize=(w * ncols, h), squeeze=False)
    return fig, axs[0]


def _points(ax, x, bins, label, scale=1.0):
    n, edges = np.histogram(x, bins=bins)
    c = 0.5 * (edges[1:] + edges[:-1])
    m = n > 0
    ax.errorbar(c[m], n[m] * scale, yerr=np.sqrt(n[m]) * scale, fmt="o", ms=3, lw=0.8, color=C["accent"], label=label)
    return n


def _ref_step(ax, x, bins, label, scale=1.0):
    n, edges = np.histogram(x, bins=bins)
    ax.stairs(n * scale, edges, color=C["grey"], lw=1.4, label=label)


def _labels(info):
    return f"run {info['run']:06d}", (f"reference {info['ref_run']:06d}" if info.get("ref_run") else None)


def _compare(ax, x, xr, bins, info):
    """This run as points, the reference scaled to the same number of entries."""
    lab, rlab = _labels(info)
    if xr is not None and len(xr) and rlab:
        _ref_step(ax, xr, bins, rlab, scale=len(x) / len(xr))
    _points(ax, x, bins, lab)
    ax.legend(loc="best")


def _legend_on_map(ax, loc="upper left"):
    leg = ax.legend(loc=loc, frameon=True, facecolor=C["ground"], edgecolor=C["line"], framealpha=0.9)
    return leg


def _drift_hi(dt):
    """Upper end of drift-time axes: past the cathode edge, not out to the accidental tail."""
    dt = dt[np.isfinite(dt)]
    return max(10.0, float(np.percentile(dt, 97)) * 1.3) if len(dt) else 50.0


def _finite(*a):
    ok = np.ones(len(a[0]), bool)
    for x in a:
        ok &= np.isfinite(x)
    return ok


def _note(ax, text):
    ax.text(0.02, 0.97, text, transform=ax.transAxes, va="top", ha="left", fontsize=8.5, color=C["ink2"])


def peak(x, lo_frac=0.2):
    """(mean, sigma) of the highest peak above the lowest lo_frac of the range: a Gaussian fitted in mean +- 1.5 sigma,
    three times. None when there are too few entries."""
    x = x[np.isfinite(x)]
    if len(x) < 200:
        return None
    lo, hi = np.percentile(x, [5, 99.5])
    lo = lo + lo_frac * (hi - lo)
    n, e = np.histogram(x, bins=150, range=(lo, hi))
    if n.max() < 20:
        return None
    mu = 0.5 * (e[n.argmax()] + e[n.argmax() + 1])
    sig = 0.08 * mu if mu > 0 else (hi - lo) / 20
    for _ in range(3):
        sel = x[(x > mu - 1.5 * sig) & (x < mu + 1.5 * sig)]
        if len(sel) < 50:
            return None
        mu, sig = float(np.mean(sel)), float(np.std(sel)) * 1.35     # +-1.5 sigma window: std is ~0.74 sigma
    # only a peak that stands out: the counts within +-1 sigma above the straight line through the side bands
    # (2-3 sigma on both sides) by at least 30 % and 5 standard deviations
    inner = ((x > mu - sig) & (x < mu + sig)).sum()
    side = ((x > mu - 3 * sig) & (x < mu - 2 * sig)).sum() + ((x > mu + 2 * sig) & (x < mu + 3 * sig)).sum()
    bg = side                                        # two 1-sigma bands = the 2-sigma inner window
    if inner < 1.3 * bg or inner - bg < 5 * np.sqrt(max(bg, 1)):
        return None
    return mu, sig


# ------------------------------------------------------------------------------------------------ event figures
def fig_rate(e, ref, info):
    """Is the DAQ stable (bursts, trips)?"""
    fig, (ax,) = _fig()
    t = (e["time"] - e["time"].min()) / 60e9
    width = max(10 / 60, t.max() / 40)                   # about 40 bins over the run, at least 10 s
    bins = np.arange(0, t.max() + width, width)
    n, edges = np.histogram(t, bins=bins)
    c = 0.5 * (edges[1:] + edges[:-1])
    full = edges[1:] <= t.max()                          # the last, partial bin would look like a drop
    ax.errorbar(c[full], n[full] / (60 * width), yerr=np.sqrt(n[full]) / (60 * width), fmt="o", ms=3, lw=0.8,
                color=C["accent"], label=_labels(info)[0])
    if ref is not None and len(ref) > 1 and info.get("ref_run"):
        span = (ref["time"].max() - ref["time"].min()) / 1e9
        if span > 0:
            ax.axhline(len(ref) / span, color=C["grey"], ls="--", lw=1.2, label=f"{_labels(info)[1]} (mean)")
    ax.set_xlabel("time in the run [min]")
    ax.set_ylabel("events with S1 and S2 [Hz]")
    ax.set_ylim(bottom=0)
    ax.legend(loc="lower right")
    return fig


def fig_drift(e, ref, info):
    """Gate and cathode edges where they should be (drift velocity)?"""
    fig, (ax,) = _fig()
    dt = e["drift_time"] / 1e3
    hi = _drift_hi(dt)
    _compare(ax, dt, ref["drift_time"] / 1e3 if ref is not None else None, np.linspace(0, hi, 120), info)
    ax.set_xlabel("drift time [µs]")
    ax.set_ylabel("events")
    return fig


def fig_s2_width(e, ref, info):
    """Diffusion and liquid level as expected? (S2 width grows with drift time)"""
    from matplotlib.colors import LogNorm
    fig, (ax,) = _fig()
    dt, w = e["drift_time"] / 1e3, e["s2_range_50p_area"] / 1e3
    ok = _finite(dt, w)
    if ok.sum() < 10:
        _note(ax, "too few events")
        return fig
    xhi = _drift_hi(dt[ok])
    yhi = float(np.percentile(w[ok][dt[ok] < xhi], 99.5)) * 1.2
    xb, yb = np.linspace(0, xhi, 80), np.linspace(0, yhi, 80)
    _, _, _, m = ax.hist2d(dt[ok], w[ok], bins=[xb, yb], norm=LogNorm(), cmap="viridis")
    fig.colorbar(m, ax=ax, label="events")

    def med(d, ww):
        c, y = [], []
        for a, b in zip(xb[:-1:4], xb[4::4]):
            s = ww[(d >= a) & (d < b)]
            if len(s) >= 20:
                c.append(0.5 * (a + b))
                y.append(np.median(s))
        return c, y
    lab, rlab = _labels(info)
    ax.plot(*med(dt[ok], w[ok]), color=C["orange"], lw=2, label=f"{lab} median")
    if ref is not None and rlab:
        rd, rw = ref["drift_time"] / 1e3, ref["s2_range_50p_area"] / 1e3
        rok = _finite(rd, rw)
        ax.plot(*med(rd[rok], rw[rok]), color=C["ink"], lw=1.5, ls="--", label=f"{rlab} median")
    ax.set_xlabel("drift time [µs]")
    ax.set_ylabel("S2 width (50 % area) [µs]")
    _legend_on_map(ax)
    return fig


def fig_xy(e, ref, info):
    """Dead or hot PMTs, field edges? (no cuts yet: the central blob of odd events is included)"""
    from matplotlib.colors import LogNorm
    fig, (ax,) = _fig(w=5.2, h=4.4)
    x, y = e["s2_x"], e["s2_y"]
    ok = _finite(x, y)
    if ok.sum() < 10:
        _note(ax, "too few events")
        return fig
    lim = 34.0                                           # the same range for every run: runs compare at a glance
    b = np.linspace(-lim, lim, 90)
    _, _, _, m = ax.hist2d(x[ok], y[ok], bins=[b, b], norm=LogNorm(), cmap="viridis")
    fig.colorbar(m, ax=ax, label="events")
    from matplotlib.patches import Circle
    ax.add_patch(Circle((0, 0), TPC_R_MM, fill=False, ec=C["orange"], lw=1.2, ls="--"))
    ax.set_aspect("equal")
    ax.set_xlabel("x (S2) [mm]")
    ax.set_ylabel("y (S2) [mm]")
    _note(ax, "no cuts yet")
    return fig


def fig_areas(e, ref, info):
    """S1 and S2 spectra next to the reference."""
    fig, axs = _fig(ncols=2, w=5.2)
    for ax, f, lab in ((axs[0], "s1_area", "S1"), (axs[1], "s2_area", "S2")):
        x = np.log10(e[f][e[f] > 0])
        xr = np.log10(ref[f][ref[f] > 0]) if ref is not None else None
        lo, hi = np.percentile(x, [0.2, 99.8]) if len(x) else (0, 1)
        _compare(ax, x, xr, np.linspace(lo, hi, 100), info)
        ax.set_xlabel(f"log10 {lab} area [PE]")
        ax.set_ylabel("events")
        ax.set_yscale("log")
    return fig


# ------------------------------------------------------------------------------------------------ source figures
def _energy(e):
    """('energy', keV) when the run has an energy, else ('cS2', PE)."""
    en = e["energy"] if "energy" in e.dtype.names else None
    if en is not None and np.isfinite(en).sum() > 100 and np.nanmedian(en) > 0:
        return en, "energy [keV]"
    return e["cs2"], "cS2 [PE]"


def fig_cs1_cs2(e, ref, info):
    """Anti-correlation and photopeak in the right place?"""
    from matplotlib.colors import LogNorm
    fig, (ax,) = _fig()
    a, b = e["cs1"], e["cs2"]
    ok = _finite(a, b) & (a > 0) & (b > 0)
    if ok.sum() < 50:
        _note(ax, "too few events")
        return fig
    xhi, yhi = (float(np.percentile(v[ok], 99)) * 1.1 for v in (a, b))
    _, _, _, m = ax.hist2d(a[ok], b[ok], bins=[np.linspace(0, xhi, 100), np.linspace(0, yhi, 100)], norm=LogNorm(),
                           cmap="viridis")
    fig.colorbar(m, ax=ax, label="events")
    p1, p2 = peak(a[ok]), peak(b[ok])
    if p1 and p2:
        from matplotlib.patches import Ellipse
        ax.add_patch(Ellipse((p1[0], p2[0]), 4 * p1[1], 4 * p2[1], fill=False, ec=C["orange"], lw=1.8))
        _note(ax, f"photopeak: cS1 {p1[0]:.0f} PE, cS2 {p2[0]:.3g} PE")
    else:
        _note(ax, "no clear photopeak (no cuts yet)")
    ax.set_xlabel("cS1 [PE]")
    ax.set_ylabel("cS2 [PE]")
    return fig


def fig_spectrum(e, ref, info):
    """Photopeak position and resolution, next to the reference (cS1 and cS2; a fit only where a peak stands out)."""
    fig, axs = _fig(ncols=2, w=5.2)
    for ax, f, lab in ((axs[0], "cs1", "cS1"), (axs[1], "cs2", "cS2")):
        x = e[f][np.isfinite(e[f]) & (e[f] > 0)]
        xr = ref[f][np.isfinite(ref[f]) & (ref[f] > 0)] if ref is not None else None
        if len(x) < 50:
            _note(ax, "too few events")
            continue
        bins = np.linspace(0, float(np.percentile(x, 99.5)) * 1.1, 120)
        _compare(ax, x, xr, bins, info)
        lines = []
        for which, data in (("this run", x), ("reference", xr)):
            p = peak(data) if data is not None and len(data) else None
            if not p:
                continue
            mu, sig = p
            if which == "this run":
                xx = np.linspace(mu - 2.5 * sig, mu + 2.5 * sig, 200)
                inner = ((x > mu - 1.5 * sig) & (x < mu + 1.5 * sig)).sum()
                amp = inner * (bins[1] - bins[0]) / (sig * np.sqrt(2 * np.pi) * 0.866)
                ax.plot(xx, amp * np.exp(-0.5 * ((xx - mu) / sig) ** 2), color=C["orange"], lw=2)
            lines.append(f"{which}: peak {mu:.4g} PE, σ/μ {100 * sig / mu:.1f} %")
        ax.text(0, 1.02, "\n".join(lines) if lines else "no clear photopeak (no energy in this processing; no cuts yet)",
                transform=ax.transAxes, va="bottom", ha="left", fontsize=8.5, color=C["ink2"])
        ax.set_xlabel(f"{lab} [PE]")
        ax.set_ylabel("events")
        ax.set_yscale("log")
        if ax.get_legend():
            ax.get_legend().set_loc("upper right")
    return fig


# ------------------------------------------------------------------------------------------------ LED figures
def fig_spe(e, ref, info):
    """Gains stable? Single-PE area per channel (LED windows), next to the reference LED run."""
    chans = sorted(int(c) for c in np.unique(e["channel"]))
    n = max(1, len(chans))
    ncol = min(4, n)
    nrow = int(np.ceil(n / ncol))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plotstyle.apply()
    fig, axs = plt.subplots(nrow, ncol, figsize=(3.6 * ncol, 2.8 * nrow), squeeze=False)
    lab, rlab = _labels(info)
    for k, ch in enumerate(chans):
        ax = axs[k // ncol][k % ncol]
        a = e["area"][e["channel"] == ch]
        ar = ref["area"][ref["channel"] == ch] if ref is not None and rlab else None
        lo, hi = np.percentile(a, [0.5, 99.5]) if len(a) else (0, 1)
        _compare(ax, a, ar, np.linspace(lo, hi, 80), info)
        txt = f"mean {np.mean(a):.1f}" + (f" (ref {np.mean(ar):.1f})" if ar is not None and len(ar) else "")
        ax.set_title(f"channel {ch}", fontsize=10)
        _note(ax, txt)
        ax.set_yscale("log")
        ax.set_xlabel("area [ADC·samples]")
        if ax.get_legend():
            ax.get_legend().remove()
    for k in range(n, nrow * ncol):
        axs[k // ncol][k % ncol].set_visible(False)
    fig.tight_layout()
    return fig


FIGURES = {
    "event": [("rate", "Event rate during the run", fig_rate),
              ("s2_width", "S2 width vs drift time", fig_s2_width),
              ("xy", "Position of the S2 (top array)", fig_xy),
              ("drift", "Drift time", fig_drift),
              ("areas", "S1 and S2 spectra", fig_areas)],
    "source": [("cs1_cs2", "cS1 vs cS2", fig_cs1_cs2),
               ("spectrum", "Spectrum and photopeak", fig_spectrum)],
    "led": [("spe", "Single-PE area per channel", fig_spe)],
}
QUESTIONS = {name: fn.__doc__.strip().split("\n")[0] for figs in FIGURES.values() for name, _, fn in figs}
_FN = {name: fn for figs in FIGURES.values() for name, _, fn in figs}


def make(name, e, ref, info):
    """The figure `name` of the selected events e (and reference ref), as a matplotlib Figure."""
    if name in ("spe",):
        return plotstyle.finish(_FN[name](e, ref, info))
    e = e[select(e)]
    ref = ref[select(ref)] if ref is not None else None
    return plotstyle.finish(_FN[name](e, ref, info))
