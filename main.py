"""Airfoil Finder: type an airfoil's name and it appears right away.

    python main.py            desktop window
    python main.py --web      opens in your browser instead

The same code builds for Android / iOS with `flet build` (see README.md).
"""
from __future__ import annotations

import sys

import flet as ft
import flet.canvas as cv

from airfoil_db import Airfoil, AirfoilDB

MAX_LISTED = 30        # how many matches to list under the drawing
MAX_WIDTH = 900        # content is centred and never wider than this
PAGE_PAD = 16
CARD_PAD = 12
EXAMPLES = ["NACA 2412", "E387", "Clark Y", "S1223", "NACA 0012"]

LINE = ft.Colors.BLUE_400
FILL = ft.Colors.with_opacity(0.22, ft.Colors.BLUE_400)
CHORD = ft.Colors.with_opacity(0.6, ft.Colors.GREY_500)
CAMBER = ft.Colors.ORANGE_400
POINT = ft.Colors.RED_400

db = AirfoilDB()


def _path(points, paint) -> cv.Path:
    els = [cv.Path.MoveTo(x=points[0][0], y=points[0][1])]
    els += [cv.Path.LineTo(x=x, y=y) for x, y in points[1:]]
    return cv.Path(elements=els, paint=paint)


def build_drawing(a: Airfoil, width: float, show_points: bool, show_details: bool):
    """Return (canvas shapes, canvas height) for one airfoil, drawn with true proportions."""
    pad = 20
    pts = a.points()
    ys = [y for _, y in pts]
    y_lo, y_hi = min(ys), max(ys)
    span = max(y_hi - y_lo, 1e-6)

    scale = width - 2 * pad                 # pixels per unit of chord
    if span * scale > 320:                  # very thick shapes: shrink so they fit
        scale = 320 / span
    height = max(140.0, span * scale + 2 * pad)
    x0 = (width - scale) / 2
    y_mid = height / 2
    y_c = (y_hi + y_lo) / 2

    def px(x: float) -> float:
        return x0 + x * scale

    def py(y: float) -> float:
        return y_mid - (y - y_c) * scale

    screen = [(px(x), py(y)) for x, y in pts]
    shapes: list = [
        cv.Line(
            x1=px(0), y1=py(0), x2=px(1), y2=py(0),
            paint=ft.Paint(color=CHORD, stroke_width=1, stroke_dash_pattern=[6, 5],
                           style=ft.PaintingStyle.STROKE),
        ),
        _path(screen + [screen[0]], ft.Paint(color=FILL, style=ft.PaintingStyle.FILL)),
        _path(screen + [screen[0]], ft.Paint(color=LINE, stroke_width=2, style=ft.PaintingStyle.STROKE)),
    ]

    if show_details:
        mean_line = [(px(x), py(y)) for x, y in a.camber_line(60)]
        shapes.append(_path(mean_line, ft.Paint(color=CAMBER, stroke_width=1.5,
                                                stroke_dash_pattern=[4, 3],
                                                style=ft.PaintingStyle.STROKE)))
        x, y_low, y_up = a.thickness_span()
        shapes.append(cv.Line(x1=px(x), y1=py(y_up), x2=px(x), y2=py(y_low),
                              paint=ft.Paint(color=CAMBER, stroke_width=2,
                                             style=ft.PaintingStyle.STROKE)))

    if show_points:
        shapes += [cv.Circle(x=sx, y=sy, radius=2.2,
                             paint=ft.Paint(color=POINT, style=ft.PaintingStyle.FILL))
                   for sx, sy in screen]
    return shapes, height


def stat(label: str, value: str) -> ft.Container:
    return ft.Container(
        content=ft.Column(
            [ft.Text(label, size=11, color=ft.Colors.ON_SURFACE_VARIANT),
             ft.Text(value, size=15, weight=ft.FontWeight.W_600)],
            spacing=2, tight=True,
        ),
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        border_radius=10,
        bgcolor=ft.Colors.with_opacity(0.07, ft.Colors.ON_SURFACE),
    )


def camber_text(a: Airfoil) -> str:
    if abs(a.camber) < 0.05:
        return "none (symmetric)"
    return f"{a.camber:.1f}% at {a.camber_x:.0f}%"


def main(page: ft.Page):
    page.title = "Airfoil Finder"
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.BLUE)
    page.dark_theme = ft.Theme(color_scheme_seed=ft.Colors.BLUE)
    page.padding = PAGE_PAD
    page.scroll = ft.ScrollMode.AUTO

    state: dict = {"airfoil": None, "matches": [], "points": False, "details": False}

    def content_width() -> float:
        return max(260.0, min((page.width or 420) - 2 * PAGE_PAD, MAX_WIDTH))

    # ---- the airfoil card -------------------------------------------------
    canvas = cv.Canvas(shapes=[], width=300, height=160)
    name_text = ft.Text("", size=26, weight=ft.FontWeight.BOLD, selectable=True)
    desc_text = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True)
    stats_row = ft.Row(wrap=True, spacing=8, run_spacing=8)

    def on_toggle(e):
        state["points"] = points_switch.value
        state["details"] = details_switch.value
        draw()
        page.update()

    points_switch = ft.Switch(label="Points", value=False, on_change=on_toggle)
    details_switch = ft.Switch(label="Camber line + max thickness", value=False, on_change=on_toggle)

    clipboard = ft.Clipboard()
    page.services.append(clipboard)

    async def copy_coordinates(e):
        a = state["airfoil"]
        if a is None:
            return
        await clipboard.set(a.to_dat())
        page.show_dialog(ft.SnackBar(content=ft.Text(f"{a.name} coordinates copied (.dat format)"),
                                     duration=2500))

    card = ft.Container(
        visible=False,
        padding=CARD_PAD,
        border_radius=16,
        border=ft.Border.all(1, ft.Colors.with_opacity(0.15, ft.Colors.ON_SURFACE)),
        content=ft.Column(
            [
                name_text,
                desc_text,
                ft.Container(content=canvas, alignment=ft.Alignment(0, 0)),
                ft.Row([points_switch, details_switch], wrap=True, spacing=16, run_spacing=0),
                stats_row,
                ft.Row([ft.OutlinedButton(content="Copy coordinates", icon=ft.Icons.CONTENT_COPY,
                                          on_click=copy_coordinates)]),
            ],
            spacing=10,
        ),
    )

    # ---- empty / not-found message ---------------------------------------
    def set_query(text: str):
        search.value = text
        run_search(text)

    empty_text = ft.Text("", size=15, color=ft.Colors.ON_SURFACE_VARIANT)
    empty = ft.Container(
        padding=ft.Padding.symmetric(vertical=24),
        content=ft.Column(
            [
                ft.Icon(ft.Icons.FLIGHT, size=40, color=ft.Colors.with_opacity(0.4, ft.Colors.ON_SURFACE)),
                empty_text,
                ft.Row([ft.Chip(label=ft.Text(t), on_click=lambda e, t=t: set_query(t)) for t in EXAMPLES],
                       wrap=True, spacing=8, run_spacing=8, alignment=ft.MainAxisAlignment.CENTER),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=12,
        ),
    )

    # ---- list of matches ---------------------------------------------------
    results_label = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
    results_col = ft.Column(spacing=0)
    results_box = ft.Column([results_label, results_col], visible=False, spacing=4)

    def make_tile(a: Airfoil) -> ft.ListTile:
        bits = [a.description, f"{a.thickness:.1f}% thick"]
        return ft.ListTile(
            title=ft.Text(a.name, weight=ft.FontWeight.W_600),
            subtitle=ft.Text("  ·  ".join(b for b in bits if b), size=12, max_lines=1,
                             overflow=ft.TextOverflow.ELLIPSIS),
            dense=True,
            selected=a is state["airfoil"],
            on_click=lambda e, a=a: select(a),
        )

    def render_results():
        matches = state["matches"]
        results_col.controls = [make_tile(a) for a in matches[:MAX_LISTED]]
        if len(matches) > MAX_LISTED:
            results_label.value = f"Showing {MAX_LISTED} of {len(matches)} matches. Type more to narrow it down."
        else:
            results_label.value = f"{len(matches)} matches"
        results_box.visible = len(matches) > 1

    # ---- behaviour ---------------------------------------------------------
    def draw():
        a = state["airfoil"]
        if a is None:
            return
        inner = content_width() - 2 * CARD_PAD - 2
        shapes, height = build_drawing(a, inner, state["points"], state["details"])
        canvas.shapes = shapes
        canvas.width = inner
        canvas.height = height

    def select(a: Airfoil):
        state["airfoil"] = a
        name_text.value = a.name
        desc_text.value = a.description
        desc_text.visible = bool(a.description)
        stats_row.controls = [
            stat("Max thickness", f"{a.thickness:.1f}% at {a.thickness_x:.0f}%"),
            stat("Max camber", camber_text(a)),
            stat("Points", str(a.n_points)),
        ]
        draw()
        card.visible = True
        empty.visible = False
        render_results()
        page.update()

    def run_search(text: str):
        matches = db.search(text)
        state["matches"] = matches
        if matches:
            select(matches[0])           # best match appears as you type
            return
        state["airfoil"] = None
        card.visible = False
        results_box.visible = False
        empty.visible = True
        empty_text.value = (f"No airfoil found for “{text.strip()}”. Try another spelling."
                            if text.strip() else "Type an airfoil name to see it.")
        page.update()

    def on_search(e):
        run_search(search.value or "")

    def clear(e):
        search.value = ""
        run_search("")

    search = ft.TextField(
        hint_text="Airfoil name, e.g. NACA 2412, E387, Clark Y",
        prefix_icon=ft.Icons.SEARCH,
        suffix=ft.IconButton(icon=ft.Icons.CLEAR, on_click=clear, tooltip="Clear"),
        autofocus=True,
        filled=True,
        border_radius=14,
        on_change=on_search,
        on_submit=on_search,
    )

    def on_resize(e):
        root.width = content_width()
        draw()
        page.update()

    page.on_resize = on_resize

    header = ft.Column(
        [
            ft.Row([ft.Icon(ft.Icons.FLIGHT, color=LINE), ft.Text("Airfoil Finder", size=22,
                                                                  weight=ft.FontWeight.BOLD)]),
            ft.Text(f"{len(db):,} airfoils. Start typing a name.", size=13,
                    color=ft.Colors.ON_SURFACE_VARIANT),
        ],
        spacing=2,
    )

    root = ft.Container(
        width=content_width(),
        content=ft.Column([header, search, card, empty, results_box], spacing=14,
                          horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
    )
    page.add(ft.SafeArea(content=ft.Row([root], alignment=ft.MainAxisAlignment.CENTER,
                                        vertical_alignment=ft.CrossAxisAlignment.START)))
    run_search("")


def lan_address() -> str:
    """This computer's address on the local network (what a phone on the same Wi-Fi uses)."""
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))   # nothing is sent; it just picks the right interface
        return s.getsockname()[0]
    except OSError:
        return "your-computer-ip"
    finally:
        s.close()


if __name__ == "__main__":
    if "--phone" in sys.argv:
        port = 8550
        print("\nAirfoil Finder is running.")
        print(f"  On this computer : http://localhost:{port}")
        print(f"  On your phone    : http://{lan_address()}:{port}   (same Wi-Fi as this computer)")
        print("Press Ctrl+C here to stop.\n")
        ft.run(main, view=None, host="0.0.0.0", port=port)
    elif "--web" in sys.argv:
        ft.run(main, view=ft.AppView.WEB_BROWSER)
    else:
        ft.run(main)
