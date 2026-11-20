"""Airfoil database: loading, searching and basic geometry.

Standard library only, so it works anywhere Python does (desktop, phone, web).
"""
from __future__ import annotations

import json
import math
import re
from bisect import bisect_left
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path

def _find_data_file() -> Path:
    """airfoils.json next to this file (also accepts a data/ subfolder); on phones fall back
    to the working directory."""
    here = Path(__file__).resolve().parent
    candidates = [here / "airfoils.json", here / "data" / "airfoils.json",
                  Path.cwd() / "airfoils.json", Path.cwd() / "data" / "airfoils.json"]
    return next((p for p in candidates if p.exists()), candidates[0])


DATA_FILE = _find_data_file()


def _norm(text: str) -> str:
    """'NACA 2412', 'naca-2412' and 'Naca_2412' all become 'naca2412'."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _interp(xs: list[float], ys: list[float], x: float) -> float:
    """Straight-line interpolation of y at x (xs must be increasing)."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect_left(xs, x)
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)


@dataclass(frozen=True, eq=False, slots=True)
class Airfoil:
    id: str             # file name without .dat, e.g. "naca2412"
    title: str          # first line of the original .dat file ("" if none)
    thickness: float    # max thickness, % of chord
    thickness_x: float  # where it occurs, % of chord
    camber: float       # max camber, % of chord (negative = camber downwards)
    camber_x: float     # where it occurs, % of chord
    xy: tuple           # x0, y0, x1, y1, ... Selig order: TE -> upper -> LE -> lower -> TE
    id_key: str         # normalised id, used for searching
    hay: str            # lower-case id + title, used for searching

    @property
    def name(self) -> str:
        """Display name: 'naca2412' -> 'NACA 2412', 'e387' -> 'E387'."""
        n = self.id.upper()
        return f"NACA {n[4:]}" if n.startswith("NACA") and len(n) > 4 else n

    @property
    def description(self) -> str:
        """The title line from the original file, unless it just repeats the name."""
        return "" if _norm(self.title) in ("", self.id_key) else self.title

    @property
    def n_points(self) -> int:
        return len(self.xy) // 2

    def points(self) -> list[tuple[float, float]]:
        return list(zip(self.xy[0::2], self.xy[1::2]))

    def surfaces(self) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        """(upper, lower) surfaces, both running leading edge -> trailing edge."""
        pts = self.points()
        ile = min(range(len(pts)), key=lambda i: pts[i][0])
        return pts[: ile + 1][::-1], pts[ile:]

    def camber_line(self, n: int = 60) -> list[tuple[float, float]]:
        """Mean line halfway between the upper and lower surface."""
        upper, lower = self.surfaces()
        ux, uy = [p[0] for p in upper], [p[1] for p in upper]
        lx, ly = [p[0] for p in lower], [p[1] for p in lower]
        line = []
        for k in range(n + 1):
            x = (1 - math.cos(math.pi * k / n)) / 2  # denser near the leading edge
            line.append((x, (_interp(ux, uy, x) + _interp(lx, ly, x)) / 2))
        return line

    def thickness_span(self) -> tuple[float, float, float]:
        """(x, y_lower, y_upper) at the max-thickness location, as chord fractions."""
        upper, lower = self.surfaces()
        x = self.thickness_x / 100
        ux, uy = [p[0] for p in upper], [p[1] for p in upper]
        lx, ly = [p[0] for p in lower], [p[1] for p in lower]
        return x, _interp(lx, ly, x), _interp(ux, uy, x)

    def to_dat(self) -> str:
        """Coordinates as a standard Selig-format .dat file (works with XFOIL, XFLR5, ...)."""
        lines = [self.title or self.name]
        lines += [f"  {x:.6f}  {y:.6f}" for x, y in self.points()]
        return "\n".join(lines) + "\n"


class AirfoilDB:
    def __init__(self, path: Path | str = DATA_FILE):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        self.source: str = raw.get("source", "")
        self.airfoils: list[Airfoil] = []
        for r in raw["airfoils"]:
            self.airfoils.append(
                Airfoil(
                    id=r["id"],
                    title=r.get("title", ""),
                    thickness=r["t"],
                    thickness_x=r["tx"],
                    camber=r["c"],
                    camber_x=r["cx"],
                    xy=tuple(r["xy"]),
                    id_key=_norm(r["id"]),
                    hay=f'{r["id"]} {r.get("title", "")}'.lower(),
                )
            )
        self._by_key: dict[str, list[Airfoil]] = {}
        for a in self.airfoils:
            self._by_key.setdefault(a.id_key, []).append(a)

    def __len__(self) -> int:
        return len(self.airfoils)

    def get(self, airfoil_id: str) -> Airfoil | None:
        hits = self._by_key.get(_norm(airfoil_id))
        return hits[0] if hits else None

    def search(self, query: str) -> list[Airfoil]:
        """Best matches first. Ignores case, spaces, dashes and underscores.

        'naca 2412', 'NACA-2412' and 'naca2412' all find the same airfoil, and
        a bare '2412' finds every airfoil with 2412 in its name.
        """
        q = _norm(query)
        if not q:
            return []
        tokens = re.findall(r"[a-z0-9]+", query.lower())

        scored: list[tuple[int, int, str, Airfoil]] = []
        for a in self.airfoils:
            if a.id_key == q:
                score = 0                       # exact name
            elif a.id_key.startswith(q):
                score = 1                       # name starts with what you typed
            elif q in a.id_key:
                score = 2                       # typed text is inside the name
            elif q in _norm(a.hay):
                score = 3                       # found in the description line
            elif len(tokens) > 1 and all(t in a.hay for t in tokens):
                score = 4                       # every word found somewhere
            else:
                continue
            scored.append((score, len(a.id_key), a.id_key, a))
        if scored:
            scored.sort(key=lambda s: s[:3])
            return [s[3] for s in scored]

        # Nothing matched: be forgiving about typos ("clark-y", "naca2142"...).
        close = get_close_matches(q, list(self._by_key), n=30, cutoff=0.6)
        return [a for key in close for a in self._by_key[key]]
