"""COPY of xams-sim xamssim/plotstyle.py (the shared XAMS figure style): keep in sync; change it there first.

Simulation as an open step histogram with a light band, data as points; a reference run as an open grey step histogram."""
from __future__ import annotations

# named colours: the web apps' tokens (light theme), and line colours that read on white
C = {
    "ground": "#ffffff", "inset": "#f3f4f7", "line": "#e6e8ee", "spine": "#c9cdd6",
    "ink": "#12141a", "ink2": "#4a5160", "ink3": "#5f6775",
    "accent": "#4f46e5", "blue": "#0284c7", "green": "#16a34a", "red": "#dc2626", "orange": "#ea580c",
    "yellow": "#ca8a04", "violet": "#6d5dd3", "grey": "#9aa1ad",
    "ptfe": "#a3a9b3", "liquid": "#93c5fd", "liquid2": "#bfdbfe", "gas": "#e5e7eb",
}
CYCLE = [C["accent"], C["orange"], C["green"], C["red"], C["blue"], C["violet"], C["yellow"], C["grey"]]
FONT = ["Plus Jakarta Sans", "Inter", "Helvetica Neue", "Arial", "DejaVu Sans"]

# the old dark figure colours -> their light counterparts (compose.py used these literals before 2026-11-05)
DARK_TO_LIGHT = {
    "#111b2e": C["ground"], "#0f1729": C["ground"], "#0b1220": C["ground"], "#2a3a58": C["spine"],
    "#dce7ff": C["ink"], "#9fb4d8": C["ink2"], "#8a96a8": C["ink3"], "#d9d9d9": C["ptfe"],
    "#4db6ff": C["blue"], "#f1c40f": C["yellow"], "#ff6b6b": C["red"], "#2ecc71": C["green"],
    "#f39c12": C["orange"], "#b3a7ff": C["violet"], "#1d4f7a": C["liquid"], "#2a6f97": C["liquid2"],
    "#3d3d5c": C["gas"],
}


def rc() -> dict:
    from cycler import cycler
    return {
        "figure.facecolor": C["ground"], "axes.facecolor": C["ground"], "savefig.facecolor": C["ground"],
        "axes.edgecolor": C["spine"], "axes.linewidth": 0.8, "axes.labelcolor": C["ink"], "axes.titlecolor": C["ink"],
        "axes.titleweight": "bold", "axes.titlesize": 11, "axes.labelsize": 10,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": C["line"], "grid.linewidth": 0.7, "axes.axisbelow": True,
        "axes.prop_cycle": cycler(color=CYCLE),
        "xtick.color": C["ink2"], "ytick.color": C["ink2"], "xtick.labelsize": 9, "ytick.labelsize": 9,
        "text.color": C["ink"], "legend.frameon": False, "legend.fontsize": 8.5, "legend.labelcolor": C["ink2"],
        "font.family": "sans-serif", "font.sans-serif": FONT, "image.cmap": "viridis",
    }


def apply():
    import matplotlib
    matplotlib.rcParams.update(rc())


def style_axes(ax):
    ax.set_facecolor(C["ground"])
    for name, sp in ax.spines.items():
        sp.set_color(C["spine"])
        if name in ("top", "right"):
            sp.set_visible(False)
    ax.tick_params(colors=C["ink2"])
    ax.xaxis.label.set_color(C["ink"])
    ax.yaxis.label.set_color(C["ink"])
    ax.title.set_color(C["ink"])


def finish(fig):
    """Before saving: no grid over images, colour maps (pcolormesh, hist2d) and colour bars."""
    from matplotlib.collections import QuadMesh
    for ax in fig.axes:
        if ax.images or any(isinstance(c, QuadMesh) for c in ax.collections) or hasattr(ax, "_colorbar"):
            ax.grid(False)
    return fig
