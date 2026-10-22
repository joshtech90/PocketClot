#!/usr/bin/env python3
"""Exportiert das Icon "Nordic Soft" (Entscheidung vom 22.10.2026) in alle
App- und Web-Ressourcen.

Quelle ist `Animation/nordic_soft_master.png`: der blaue Klumpen aus Astras
Entwurfsrunde, freigestellt auf transparentem Grund (gpt-image-2). Daraus
entstehen:

- Adaptive Icon: Vordergrund, Monochrom (108dp) und ein heller Verlauf als
  Hintergrund, wie im Entwurf.
- Legacy-Launcher (48dp), eckig und rund, vorgerendert.
- Markenzeichen `ic_brand_mark` (24dp) fuer App-Kopf und Ruhezustand der
  Denk-Animation.
- Web: `webui/brand-mark.png` (96 px) und `assets/logo.png` fuer die README.
- Play-Store-Icon 512 px unter `Animation/icons/nordic_soft/`.

Aufruf (braucht Pillow und numpy): python3 Animation/export_nordic_icons.py
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = os.path.join(ROOT, "Animation", "nordic_soft_master.png")
RES = os.path.join(ROOT, "app", "app", "src", "main", "res")
WEB_MARK = os.path.join(ROOT, "server", "pocket_claude", "webui", "brand-mark.png")
README_LOGO = os.path.join(ROOT, "assets", "logo.png")
PLAYSTORE = os.path.join(ROOT, "Animation", "icons", "nordic_soft", "playstore_512.png")

ADAPTIVE_FRACTION = 0.52   # 108dp-Viewport, Safe Zone waere 0.61
BRAND_FRACTION = 0.92      # freistehendes Markenzeichen
LEGACY_TILE_FRACTION = 0.85
LEGACY_BLOB_OF_TILE = 0.66
DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}

# Heller Hintergrund wie im Entwurf (#F1F6FB), oben etwas heller, unten
# minimal kuehler, damit die Kachel nicht flach wirkt.
BG_TOP = (0xF6, 0xF9, 0xFD)
BG_BOTTOM = (0xE3, 0xEC, 0xF6)


def clean_master() -> Image.Image:
    """Streupixel mit fast null Deckkraft entfernen und auf das Motiv zuschneiden."""
    arr = np.array(Image.open(MASTER).convert("RGBA"))
    alpha = arr[:, :, 3]
    alpha[alpha < 10] = 0
    arr[:, :, 3] = alpha
    img = Image.fromarray(arr, "RGBA")
    return img.crop(img.getbbox())


def place(blob: Image.Image, canvas: int, fraction: float) -> Image.Image:
    """Motiv zentriert auf transparente Flaeche, laengste Kante = fraction."""
    target = max(1, int(round(canvas * fraction)))
    w, h = blob.size
    scale = target / max(w, h)
    new = blob.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    out.alpha_composite(new, dest=((canvas - new.size[0]) // 2, (canvas - new.size[1]) // 2))
    return out


def gradient(size: int) -> Image.Image:
    t = np.linspace(0.0, 1.0, size)[:, None]
    top, bottom = np.array(BG_TOP, float), np.array(BG_BOTTOM, float)
    rows = (top * (1 - t) + bottom * t).astype(np.uint8)
    rgb = np.repeat(rows[:, None, :], size, axis=1)
    alpha = np.full((size, size, 1), 255, np.uint8)
    return Image.fromarray(np.concatenate([rgb, alpha], axis=2), "RGBA")


def rounded_mask(size: int, radius_frac: float) -> Image.Image:
    m = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle(
        (0, 0, size * 4 - 1, size * 4 - 1), radius=int(size * 4 * radius_frac), fill=255
    )
    return m.resize((size, size), Image.LANCZOS)


def circle_mask(size: int) -> Image.Image:
    m = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(m).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    return m.resize((size, size), Image.LANCZOS)


def tile(blob: Image.Image, size: int, mask: Image.Image) -> Image.Image:
    t = gradient(size)
    t.alpha_composite(place(blob, size, LEGACY_BLOB_OF_TILE))
    t.putalpha(mask)
    return t


def main() -> None:
    blob = clean_master()
    written = 0

    for dens, factor in DENSITIES.items():
        folder = os.path.join(RES, f"drawable-{dens}")

        canvas = int(round(108 * factor))
        fg = place(blob, canvas, ADAPTIVE_FRACTION)
        fg.save(os.path.join(folder, "ic_launcher_foreground.png"))
        gradient(canvas).save(os.path.join(folder, "ic_launcher_background.png"))

        mono = np.zeros((canvas, canvas, 4), dtype=np.uint8)
        mono[:, :, :3] = 255
        mono[:, :, 3] = np.array(fg)[:, :, 3]
        Image.fromarray(mono, "RGBA").save(os.path.join(folder, "ic_launcher_monochrome.png"))

        bm = int(round(24 * factor))
        place(blob, bm, BRAND_FRACTION).save(os.path.join(folder, "ic_brand_mark.png"))
        written += 4

        leg = int(round(48 * factor))
        tile_px = int(round(leg * LEGACY_TILE_FRACTION))
        for name, mask in (
            ("ic_launcher.png", rounded_mask(tile_px, 0.22)),
            ("ic_launcher_round.png", circle_mask(tile_px)),
        ):
            out = Image.new("RGBA", (leg, leg), (0, 0, 0, 0))
            out.alpha_composite(tile(blob, tile_px, mask), dest=((leg - tile_px) // 2,) * 2)
            out.save(os.path.join(RES, f"mipmap-{dens}", name))
            written += 1

    place(blob, 96, BRAND_FRACTION).save(WEB_MARK)
    tile(blob, 512, rounded_mask(512, 0.22)).save(README_LOGO)
    os.makedirs(os.path.dirname(PLAYSTORE), exist_ok=True)
    # Play Store maskiert selbst: volle Kachel ohne eigene Rundung.
    full = gradient(512)
    full.alpha_composite(place(blob, 512, LEGACY_BLOB_OF_TILE))
    full.save(PLAYSTORE)
    written += 3
    print(f"{written} Dateien geschrieben.")


if __name__ == "__main__":
    main()
