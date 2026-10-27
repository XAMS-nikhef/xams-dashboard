"""Two-page note: how the configuration works. Page 1, private: from the launcher tile via the settings file to the
analysis code that defines the context, and how a data set gets its status (current / outdated / unknown). Page 2,
production: what starts the processing, where the corrections versions come from, what is written where, and how the
production dashboard judges it.
House style of the XAMS notes (reportlab).
Usage (any python with reportlab): python docs/notes/make_processing_config_note.py [docs/notes/XAMS_processing_config.pdf]"""
import sys
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FD = "/System/Library/Fonts/Supplemental/"
pdfmetrics.registerFont(TTFont("Arial", FD + "Arial.ttf")); pdfmetrics.registerFont(TTFont("Arial-Bold", FD + "Arial Bold.ttf"))
pdfmetrics.registerFont(TTFont("Arial-Italic", FD + "Arial Italic.ttf"))
registerFontFamily("Arial", normal="Arial", bold="Arial-Bold", italic="Arial-Italic", boldItalic="Arial-Bold")
NAVY, LIGHT, GREEN, AMBER, RED, GRID, GREY = (colors.HexColor(c) for c in
                                              ("#1F3A5F", "#E8EEF5", "#E3F2E1", "#FFF4D6", "#FBE3E3", "#9AA8B8", "#4A5A6A"))
ss = getSampleStyleSheet()
base = ParagraphStyle("b", parent=ss["Normal"], fontName="Arial", fontSize=8.6, leading=11.2)
small = ParagraphStyle("s", parent=base, fontSize=7.6, leading=9.4)
h1 = ParagraphStyle("h1", parent=base, fontName="Arial-Bold", fontSize=15, leading=18, textColor=NAVY)
sub = ParagraphStyle("sub", parent=base, fontSize=8.8, textColor=GREY, spaceAfter=4)
h2 = ParagraphStyle("h2", parent=base, fontName="Arial-Bold", fontSize=10.5, leading=13, textColor=NAVY, spaceBefore=5, spaceAfter=2)
hdr = ParagraphStyle("hdr", parent=small, fontName="Arial-Bold", textColor=colors.white)
W = A4[0] - 26 * mm
C = "<font face='Courier'>{}</font>".format


# ------------------------------------------------------------------------------------------------ the diagram
def card(d, x, y, w, h, title, lines, fill, mono=()):
    """A box with a bold title and lines below it (lines whose index is in mono in Courier)."""
    d.add(Rect(x, y, w, h, rx=4, ry=4, fillColor=fill, strokeColor=GRID, strokeWidth=0.7))
    d.add(String(x + 6, y + h - 11, title, fontName="Arial-Bold", fontSize=8.2, fillColor=NAVY))
    for i, t in enumerate(lines):
        d.add(String(x + 6, y + h - 22 - 9.4 * i, t, fontName="Courier" if i in mono else "Arial", fontSize=6.9,
                     fillColor=colors.black))


def arrow(d, x1, y1, x2, y2, label="", dx=4, dy=0):
    d.add(Line(x1, y1, x2, y2, strokeColor=NAVY, strokeWidth=1))
    import math
    a = math.atan2(y2 - y1, x2 - x1)
    p = [x2, y2, x2 - 6 * math.cos(a - 0.4), y2 - 6 * math.sin(a - 0.4), x2 - 6 * math.cos(a + 0.4), y2 - 6 * math.sin(a + 0.4)]
    d.add(Polygon(p, fillColor=NAVY, strokeColor=NAVY))
    if label:
        d.add(String((x1 + x2) / 2 + dx, (y1 + y2) / 2 + dy, label, fontName="Arial-Italic", fontSize=6.6, fillColor=GREY))


def chip(d, x, y, text, fill):
    w = 7 + pdfmetrics.stringWidth(text, "Arial-Bold", 6.8)
    d.add(Rect(x, y, w, 12, rx=6, ry=6, fillColor=fill, strokeColor=GRID, strokeWidth=0.6))
    d.add(String(x + 3.5, y + 3.3, text, fontName="Arial-Bold", fontSize=6.8, fillColor=NAVY))
    return w


def diagram():
    w, h = W, 330
    d = Drawing(w, h)
    # row 1: launcher -> app -> settings
    card(d, 0, 278, 128, 46, "1  Launcher (your Mac)", ["tile 'Processing dashboard", "(private)': tunnel + token"], LIGHT)
    card(d, 150, 278, 150, 46, "2  Private dashboard (STBC)", ["your checkout of xams-dashboard", "ops/start_private.sh"], LIGHT)
    card(d, 322, 252, w - 322, 72, "3  Settings  ~/.xams/private.json", [
        '"strax_folder": .../measurements/strax_data',
        '"contexts": [ SR2026.3, SR2026.2, MC ]',
        '"token", "dashboard_port"',
        "only pointers: which function makes the", "context of a run (each in its own process)"], LIGHT, mono=(0, 1, 2))
    arrow(d, 128, 301, 150, 301)
    arrow(d, 300, 301, 322, 301, "reads", -10, 4)

    # row 2: the three providers
    y2 = 182
    pw = (w - 2 * 10) / 3
    provs = [("SR2026.3", ["analysis_SR2026.3/lib/xams_sr.py", "context_for_runs([run])", "all runs it knows"]),
             ("SR2026.2", ["analysis_SR2026.2/lib/xams_sr.py", "context_for_runs([run])", "all runs it knows"]),
             ("MC (SR2026.3, P1)", ["analysis_SR2026.3/lib/xams_sr.py", 'context("P1")', "only runs 990000-999999"])]
    for i, (name, lines) in enumerate(provs):
        x = i * (pw + 10)
        card(d, x, y2, pw, 52, f"4  provider: {name}", lines, AMBER, mono=(0, 1))
        arrow(d, 322 + (w - 322) / 2, 252, x + pw / 2, y2 + 52)

    # row 3: what the function uses
    y3 = 82
    card(d, 0, y3, w * 0.62, 78, "5  The context = your analysis code  (lib/xams_sr.py)", [
        "st = amstrax.contexts.xams(output_folder=strax_data)",
        "st.set_config(processing.json + gains of the period)",
        "SR2026.2 also: corrections v2 as base, field settings (drift times, velocity)",
        "config/runs/<date>.csv: run → gain period; a run not in it → 'unknown'",
        "config/gains.csv: gains per period · config/processing.json: cuts, event window",
        "installed amstrax: plugin versions and defaults (e.g. position map pos_rec_map_v1)"],
        GREEN, mono=(0, 1))
    for i in range(3):
        arrow(d, i * (pw + 10) + pw / 2, y2, min(i * (pw + 10) + pw / 2, w * 0.6), y3 + 78)
    card(d, w * 0.62 + 10, y3, w * 0.38 - 10, 78, "6  Same context also makes the data", [
        "st = xs.context_for_runs([run])",
        "st.make(run, 'event_basics')",
        "-> writes <run>-<type>-<hash> into",
        "    measurements/strax_data",
        "(the dashboard judges with what you process with)"], GREEN, mono=(0, 1, 2, 3))

    # row 4: status
    y4 = 0
    card(d, 0, y4, w, 66, "7  Status of every data set in the folder", [
        "hash in the folder name  vs  hash the provider's context would make now for that run and data type",
        "", "", "",
        "'why?' next to an outdated data set: which plugin version / setting changed, old -> new"], LIGHT)
    arrow(d, w * 0.31, y3, w * 0.31, y4 + 66)
    arrow(d, w * 0.81, y3, w * 0.81, y4 + 66)
    x = 8
    for text, fill, expl in (("current", GREEN, "a provider makes exactly this"),
                             ("outdated", RED, "made differently now"),
                             ("unknown", LIGHT, "no provider knows run / type"),
                             ("incomplete", AMBER, "strax did not finish (_temp)")):
        cw = chip(d, x, 22, text, fill)
        d.add(String(x + cw + 3, 25.3, expl, fontName="Arial", fontSize=6.6, fillColor=colors.black))
        x += cw + 14 + pdfmetrics.stringWidth(expl, "Arial", 6.6)
    return d


def diagram_production():
    w, h = W, 330
    d = Drawing(w, h)
    # row 1: launcher -> dashboard ; the two ways processing starts
    card(d, 0, 278, 128, 46, "1  Launcher (your Mac)", ["tile 'Processing dashboard':", "tunnel via xams to stbc-i1:8070"], LIGHT)
    card(d, 150, 278, 150, 46, "2  Production dashboard", ["xamsdata, ~xamsdata/xams-dashboard", "screen xams_dashboard (stbc-i1)"], LIGHT)
    card(d, 322, 252, w - 322, 72, "3  What starts processing", [
        "a) online loop (stbc-i2, screen",
        "   xams_auto_processing_online):",
        "   new runs, corrections PROD0",
        "b) dashboard 'Submit': targets,",
        "   corrections version, amstrax ref"], LIGHT)
    arrow(d, 128, 301, 150, 301)
    arrow(d, 300, 301, 322, 301, "Submit", -12, 4)

    # row 2: auto_processing -> condor ; corrections
    y2 = 182
    card(d, 0, y2, w * 0.47, 52, "4  auto_processing.py -> condor (xamsdata)", [
        "amstrax/auto_processing_new: one job per run (process.py)",
        "production amstrax checkout: /data/xenon/xams_v2/software/amstrax",
        "status + history written to the run document"], AMBER)
    card(d, w * 0.47 + 10, y2, w * 0.53 - 10, 52, "corrections version = a file in amstrax_files", [
        "corrections/_global/_global_<version>.json: option -> file",
        "  PROD0: gain_to_pe_array_v3, pos_rec_map_v1 (rest: defaults)",
        "  v4: 20 options (gains, elife, drift, cuts, posrec, ...)"], AMBER, mono=(0,))
    arrow(d, 322 + (w - 322) / 2, 252, w * 0.25, y2 + 52)

    # row 3: the context ; MC / LED
    y3 = 82
    card(d, 0, y3, w * 0.62, 78, "5  The context = amstrax + a corrections version", [
        "st = amstrax.contexts.xams(output_folder=xams_processed,",
        "                           corrections_version=PROD0 | v4 | ...)",
        "no version ('online'): amstrax defaults only (no gains: ADC·samples)",
        "files read from GitHub amstrax_files master when the context is made",
        "installed amstrax: plugin versions and defaults (PeakPositions 2.1.0)",
        "LED runs: amstrax.contexts.xams_led (records_led, led_calibration)"], GREEN, mono=(0, 1))
    arrow(d, w * 0.235, y2, w * 0.3, y3 + 78)
    arrow(d, w * 0.47 + 10 + (w * 0.53 - 10) / 2, y2, w * 0.55, y3 + 78)
    card(d, w * 0.62 + 10, y3, w * 0.38 - 10, 78, "6  Written and registered", [
        "xams_processed/<run>-<type>-<hash>",
        "(raw: xams_raw_records)",
        "run document (runs_gas): data[]",
        "{type, hash, corrections_version,", "location}, processing_status",
        "MC (xams-sim): mc_*, runs_mc, MC1"], GREEN, mono=(0, 1))
    arrow(d, w * 0.62, y3 + 39, w * 0.62 + 10, y3 + 39)

    # row 4: status in the dashboard
    y4 = 0
    card(d, 0, y4, w, 66, "7  Status in the production dashboard", [
        "run list: 'up to date' = event_info of the run's newest corrections version vs what the installed amstrax",
        "                makes with that version (only event_info)",
        "Inspect: every data set on disk vs the context of the corrections version recorded in data[]:",
        "                'loadable' or 'older product: reprocess'",
        "(no 'why?' yet: see docs/UNIFIED_DASHBOARD_REPORT.md)"], LIGHT)
    arrow(d, w * 0.31, y3, w * 0.31, y4 + 66)
    arrow(d, w * 0.81, y3, w * 0.81, y4 + 66)
    return d


def table(data, widths):
    dd = [[Paragraph(str(c), hdr if i == 0 else small) for c in r] for i, r in enumerate(data)]
    t = Table(dd, colWidths=widths)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, GRID), ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2)] +
                          [("BACKGROUND", (0, i), (-1, i), LIGHT) for i in range(2, len(data), 2)]))
    return t


def main(out):
    story = [
        Paragraph("How the private configuration works", h1),
        Paragraph("Private dashboard and private processing on STBC — who defines what. XAMS, 27 October 2026.", sub),
        Paragraph("<b>One idea:</b> the dashboard defines nothing itself. It asks <b>your analysis code</b> which context "
                  "it uses for a run, and compares that with what is in your strax folder. The same function makes your "
                  "data when you process, so \"current\" means: what you would make now.", base),
        Spacer(1, 6),
        diagram(),
        Spacer(1, 4),
        Paragraph("What to change where", h2),
        table([
            ["You want …", "Change", "Effect in the dashboard"],
            ["new gains for a period", f"{C('config/gains.csv')} (analysis repo)",
             "data processed with the old gains of that period become <i>outdated</i>; 'why?' shows gain_to_pe_array"],
            ["other cuts / event window", f"{C('config/processing.json')}", "the affected data types become <i>outdated</i>"],
            ["a new run judged", f"a row in {C('config/runs/&lt;date&gt;.csv')}", "its data sets go from <i>unknown</i> to current / outdated"],
            ["a new analysis (e.g. SR2026.4)", f"one more entry in {C('contexts')} of {C('~/.xams/private.json')}",
             "its runs are judged by its own code; restart the app (ops/start_private.sh)"],
            ["keep a deliberate variant (other cuts, a study)", "'keep' in the dashboard", "never deleted, also not by 'delete all outdated'"],
            ["new amstrax (plugins)", "central (xamsdata), not you", "data whose plugins changed become <i>outdated</i> (e.g. PeakPositions 1.2 → 2.1)"],
        ], [W * 0.26, W * 0.32, W * 0.42]),
        Spacer(1, 4),
        Paragraph("Where the files are", h2),
        table([
            ["What", "Where (STBC; the analysis repos are mirrored on the Mac in XAMS/measurements/)"],
            ["settings (pointers, token)", f"{C('~/.xams/private.json')} — only readable by you"],
            ["context definition", f"{C('measurements/analysis_SR2026.3/lib/xams_sr.py')} {C('context()')} / {C('context_for_runs()')}; "
                                   f"SR2026.2 the same, plus field settings and corrections v2"],
            ["inputs of the context", f"{C('config/runs/')}, {C('config/gains.csv')}, {C('config/processing.json')} of that analysis "
                                      "(the dashboard watches these folders and recomputes by itself)"],
            ["your data", f"{C('measurements/strax_data/&lt;run&gt;-&lt;type&gt;-&lt;hash&gt;')}; dashboard files there: "
                          f"{C('.dashboard_lineage.json')} (cache), {C('.dashboard_keep.json')}, {C('.dashboard_deletions.log')}"],
            ["the app", f"{C('users/acolijn/software/xams-dashboard')} (your checkout), screen {C('xams_dashboard_private')}"],
        ], [W * 0.26, W * 0.74]),
    ]
    story += [
        PageBreak(),
        Paragraph("How the production configuration works", h1),
        Paragraph("Central processing on STBC (xamsdata) and the production dashboard — who defines what. XAMS, 27 October 2026.", sub),
        Paragraph("<b>The difference with private:</b> the context is not defined by your analysis code but by "
                  "<b>amstrax + a corrections version</b> from amstrax_files (e.g. PROD0), and every processed data set is "
                  "<b>registered in the run database</b> (data[]). Same strax mechanism: folder name = lineage hash.", base),
        Spacer(1, 6),
        diagram_production(),
        Spacer(1, 4),
        Paragraph("What to change where", h2),
        table([
            ["You want …", "Change", "Effect"],
            ["new gains in production", f"new {C('gain_to_pe_array_vN.json')} + a new global version (e.g. PROD1) in amstrax_files "
             "(after the private analysis; you commit)", "new contexts with that version make new data; older data stay "
             "registered with their version"],
            ["a new position map", f"new {C('pos_rec_map_vN.json')} + global version", "PeakPositions and everything after it change"],
            ["the version the online loop uses", f"{C('XAMS_AUTOPROC_CORRECTIONS')} in {C('ops/start_autoprocess_online.sh')} (default PROD0); "
             "restart the loop (xamsdata, explicit OK)", "new runs are processed with it"],
            ["a plugin change", f"amstrax PR, then {C('git pull')} of the production checkout (xamsdata, explicit OK)",
             "data made before become 'older product' (e.g. PeakPositions 1.2 → 2.1)"],
            ["reprocess runs", "dashboard: select runs → Submit (targets, corrections version)", "condor jobs, data[] and history updated"],
            ["careful", f"amstrax_files is read from GitHub {C('master')} when a context is made", "a commit there changes "
             "production at once for that version: make a new version instead of editing an existing one"],
        ], [W * 0.22, W * 0.43, W * 0.35]),
        Spacer(1, 4),
        Paragraph("Where the files are", h2),
        table([
            ["What", "Where (STBC)"],
            ["amstrax (production)", f"{C('/data/xenon/xams_v2/software/amstrax')}; loop in {C('amstrax/auto_processing_new/')}"],
            ["corrections", f"GitHub XAMS-nikhef/amstrax_files: {C('corrections/_global/_global_&lt;version&gt;.json')} and "
                            f"{C('corrections/&lt;option&gt;/&lt;file&gt;.json')} (per run range)"],
            ["data", f"{C('xams_raw_records/')}, {C('xams_processed/')} (MC: {C('mc_raw_records/')}, {C('mc_processed/')}) "
                     f"under {C('/data/xenon/xams_v2/')}; logs in {C('logs/')}"],
            ["run database", f"{C('run.runs_gas')} (MC: {C('run.runs_mc')}): data[], processing_status, processing_history"],
            ["dashboard", f"{C('~xamsdata/xams-dashboard')} (branch master-xams), screen {C('xams_dashboard')} on stbc-i1, port 8070; "
                          f"online loop: screen {C('xams_auto_processing_online')} on stbc-i2"],
        ], [W * 0.22, W * 0.78]),
    ]
    SimpleDocTemplate(str(out), pagesize=A4, leftMargin=13 * mm, rightMargin=13 * mm, topMargin=11 * mm, bottomMargin=9 * mm,
                      title="How the private and production configuration work", author="XAMS").build(story)
    print("wrote", out)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("XAMS_processing_config.pdf"))
