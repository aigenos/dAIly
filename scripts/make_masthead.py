"""Generate the baked dAIly hero masthead (docs/assets/hero-masthead.png).

The hero is a baked IMAGE (not CSS) so no mail client can recolor or smart-invert
it. Palette: a horizontal gradient that holds emerald through the first ~20%
(behind the logo + wordmark) then eases into dark navy, with a subtle cyan
"neural constellation" in the dark right half. The "AI" in dAIly is italic mint.

Run:  python -m scripts.make_masthead   (writes docs/assets/hero-masthead.png)
"""

from __future__ import annotations

import base64
import os

import cairosvg

W, H = 1440, 380
ASSETS = os.path.join(os.path.dirname(__file__), "..", "docs", "assets")
LOGO = os.path.join(ASSETS, "aigenos-logo-dark.png")
OUT = os.path.join(ASSETS, "hero-masthead.png")

FONT = "Liberation Sans, DejaVu Sans, Arial, sans-serif"

# Neural constellation nodes (x, y) in the dark right half, plus the edges that
# connect them. Kept faint so the wordmark stays the focus.
_NODES = [
    (905, 150), (1010, 75), (1055, 165), (1110, 250), (1160, 120),
    (1215, 300), (1265, 160), (1320, 205), (1360, 80), (1370, 285),
]
_EDGES = [
    (0, 1), (1, 2), (2, 3), (0, 3), (1, 4), (4, 6), (6, 7), (7, 5),
    (3, 5), (6, 8), (7, 9), (8, 4),
]


def _constellation() -> str:
    parts = []
    for a, b in _EDGES:
        x1, y1 = _NODES[a]
        x2, y2 = _NODES[b]
        parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            'stroke="#38bdf8" stroke-opacity="0.22" stroke-width="1.2"/>'
        )
    for x, y in _NODES:
        parts.append(f'<circle cx="{x}" cy="{y}" r="3" fill="#7dd3fc" fill-opacity="0.55"/>')
    return "\n".join(parts)


def _logo_data_uri() -> str:
    with open(LOGO, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def build_svg() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" \
viewBox="0 0 {W} {H}" font-family="{FONT}">
  <defs>
    <!-- Predominantly dark navy/black. Only a faint emerald tint at the far
         left, dissolving into near-black navy across the rest. -->
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="0.5">
      <stop offset="0%" stop-color="#0d211f"/>
      <stop offset="18%" stop-color="#0a141c"/>
      <stop offset="55%" stop-color="#080e16"/>
      <stop offset="100%" stop-color="#05070d"/>
    </linearGradient>
    <radialGradient id="glow" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#10b981" stop-opacity="0.16"/>
      <stop offset="100%" stop-color="#10b981" stop-opacity="0"/>
    </radialGradient>
  </defs>

  <rect width="{W}" height="{H}" fill="url(#bg)"/>
  {_constellation()}

  <!-- Logo mark on a soft emerald glow -->
  <circle cx="128" cy="190" r="70" fill="url(#glow)"/>
  <circle cx="128" cy="190" r="52" fill="#ffffff" fill-opacity="0.06"
          stroke="#6ee7b7" stroke-opacity="0.35" stroke-width="1.5"/>
  <image href="{_logo_data_uri()}" x="88" y="150" width="80" height="80"/>

  <!-- Kicker -->
  <text x="246" y="150" font-size="20" font-weight="700" letter-spacing="5"
        fill="#ffffff" fill-opacity="0.72">BY AIGENOS · DAILY AI INTELLIGENCE</text>

  <!-- Wordmark: white d…ly, italic mint AI -->
  <text x="244" y="238" font-size="72" font-weight="800" letter-spacing="-1"
        fill="#ffffff">d<tspan font-style="italic" fill="#6ee7b7">AI</tspan>ly</text>

  <!-- Subtitle -->
  <text x="248" y="300" font-size="24" font-weight="500" fill="#ffffff"
        fill-opacity="0.82">Your daily AI intelligence briefing — what's new, \
what to read, what to build.</text>
</svg>"""


def main() -> None:
    cairosvg.svg2png(
        bytestring=build_svg().encode("utf-8"),
        write_to=OUT,
        output_width=W,
        output_height=H,
    )
    print(f"wrote {OUT} ({W}x{H})")


if __name__ == "__main__":
    main()
