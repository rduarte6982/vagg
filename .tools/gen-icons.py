"""Renderiza o VAGG mark em PNG (Wails) e ICO (Inno Setup) sem precisar de
libcairo. Desenha o logo direto em raster com Pillow.

Saída:
  clients/windows/build/appicon.png       — 1024x1024 (Wails build embed)
  clients/windows/build/icon.ico          — multi-res 16/32/48/64/128/256
  clients/windows/build/windows/icon.ico  — copia idêntica
  ui/public/favicon-32.png                — 32x32 fallback pra browsers velhos
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

# ── VAGG palette ─────────────────────────────────────────────
BG = (11, 13, 16, 255)              # #0b0d10
NODE = (182, 187, 194, 255)         # #b6bbc2
WIRE = (122, 128, 138, 255)         # #7a808a
# signal-green oklch(78% 0.16 162) ≈ sRGB
SIGNAL = (52, 200, 150, 255)        # #34c896 (aprox)


def render(size: int, *, rounded: bool = True) -> Image.Image:
    """Desenha o mark em ``size``x``size``. Mantém proporção do brand:
    base 28 → escala uniforme."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # bg arredondado
    if rounded:
        radius = max(int(size * 0.18), 1)
        # rounded rectangle via mask
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, size, size), radius=radius, fill=255)
        bg = Image.new("RGBA", (size, size), BG)
        img.paste(bg, (0, 0), mask)
    else:
        d.rectangle((0, 0, size, size), fill=BG)

    # escala: brand original 28x28 → este tamanho
    s = size / 28.0

    # 4 nodes em (4,4) (24,4) (4,24) (24,24), raio 2
    node_r = max(int(2 * s), 1)
    for cx_o, cy_o in [(4, 4), (24, 4), (4, 24), (24, 24)]:
        cx, cy = int(cx_o * s), int(cy_o * s)
        d.ellipse((cx - node_r, cy - node_r, cx + node_r, cy + node_r), fill=NODE)

    # 4 wires conectando node ao center (14,14)
    wire_w = max(int(1.4 * s), 1)
    cx_c, cy_c = int(14 * s), int(14 * s)
    for cx_o, cy_o in [(4, 4), (24, 4), (4, 24), (24, 24)]:
        cx, cy = int(cx_o * s), int(cy_o * s)
        d.line((cx, cy, cx_c, cy_c), fill=WIRE, width=wire_w)

    # core (aggregator) — rect (10,10)→(18,18) com cantos arredondados
    core_x0, core_y0 = int(10 * s), int(10 * s)
    core_x1, core_y1 = int(18 * s), int(18 * s)
    core_r = max(int(1.6 * s), 1)
    d.rounded_rectangle((core_x0, core_y0, core_x1, core_y1), radius=core_r, fill=SIGNAL)

    return img


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    client_build = repo / "clients" / "windows" / "build"
    client_build.mkdir(parents=True, exist_ok=True)
    (client_build / "windows").mkdir(exist_ok=True)

    # 1) Wails embed — 1024 PNG
    big = render(1024, rounded=True)
    big.save(client_build / "appicon.png", "PNG")
    print(f"wrote {client_build / 'appicon.png'}")

    # 2) ICO multi-res — Pillow gera todas as resoluções num único .ico
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = render(256, rounded=True)
    ico_path = client_build / "icon.ico"
    base.save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
    )
    print(f"wrote {ico_path}")

    # cópia em windows/ (caminho que o Wails procura)
    base.save(
        client_build / "windows" / "icon.ico",
        format="ICO",
        sizes=[(s, s) for s in sizes],
    )
    print(f"wrote {client_build / 'windows' / 'icon.ico'}")

    # 3) Favicons PNG fallback (browsers que não rendem oklch no SVG)
    ui_public = repo / "ui" / "public"
    if ui_public.exists():
        for size in (32, 96, 192, 512):
            render(size).save(ui_public / f"favicon-{size}.png", "PNG")
            print(f"wrote {ui_public / f'favicon-{size}.png'}")

    portal_public = repo / "portal" / "public"
    if portal_public.exists():
        for size in (32, 192):
            render(size).save(portal_public / f"favicon-{size}.png", "PNG")
            print(f"wrote {portal_public / f'favicon-{size}.png'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
