#!/usr/bin/env python3
"""Exportiert das Icon "Nordic Soft" (Entscheidung vom 22.10.2026) in alle
App- und Web-Ressourcen.

Quelle ist `Animation/nordic_soft_master.png`: der blaue Klumpen aus Astras
Entwurfsrunde, freigestellt auf transparentem Grund (gpt-image-2). Daraus
entstehen:

- Adaptive Icon: Vordergrund, Monochrom (108dp) und ein heller Verlauf als
  Hintergrund, wie im Entwurf.
- Legacy-Launcher (48dp), eckig und rund, vorgerendert.
- Markenzeichen `ic_brand_mark` (96dp) fuer App-Kopf, Erststart und
  Ruhezustand der Denk-Animation.
- Statusleisten-Symbol `drawable/ic_notification.xml` aus der vermessenen Kontur.
- Web: `webui/brand-mark.png` (96 px, auch Favicon), `webui/apple-touch-icon.png`
  (180 px) und `assets/logo.png` fuer die README.
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
WEB_TOUCH = os.path.join(ROOT, "server", "pocket_claude", "webui", "apple-touch-icon.png")
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


def contour_radii(blob: Image.Image, steps: int = 36) -> tuple[list[float], float, float]:
    """Kontur als Radien im 10-Grad-Raster, ab 3 Uhr im Uhrzeigersinn.

    Einheit wie in PocketThinkingBlob.kt: relativ zu baseRadius (0.36 der
    Flaeche), wenn das Motiv wie ic_brand_mark 92 % der Flaeche einnimmt.
    Dazu der Versatz des Schwerpunkts zur Bildmitte in derselben Einheit.
    """
    mask = np.array(blob)[:, :, 3] > 128
    ys, xs = np.nonzero(mask)
    cx, cy = xs.mean(), ys.mean()
    h, w = mask.shape
    half = max(w, h) / 2
    unit = (0.46 / 0.36) / half
    radii = []
    for i in range(steps):
        t = np.radians(i * 360 / steps)
        rr = np.arange(0, 2 * half, 0.25)
        x = np.rint(cx + rr * np.cos(t)).astype(int)
        y = np.rint(cy + rr * np.sin(t)).astype(int)
        ok = (x >= 0) & (x < w) & (y >= 0) & (y < h)
        hit = rr[ok][mask[y[ok], x[ok]]]
        radii.append(round(float(hit.max()) * unit, 3))
    return radii, round((cx - w / 2) / half * 0.46 / 0.36, 3), round((cy - h / 2) / half * 0.46 / 0.36, 3)


def blob_path(radii: list[float], size: float, pad: float) -> str:
    """Catmull-Rom durch die Konturpunkte als Vektor-Pfad (wie die Compose-Form)."""
    n = len(radii)
    pts = [(r * np.cos(np.radians(i * 360 / n)), r * np.sin(np.radians(i * 360 / n))) for i, r in enumerate(radii)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    s = (size - 2 * pad) / max(max(xs) - min(xs), max(ys) - min(ys))
    ox = size / 2 - s * (max(xs) + min(xs)) / 2
    oy = size / 2 - s * (max(ys) + min(ys)) / 2
    p = [(ox + s * x, oy + s * y) for x, y in pts]
    f = lambda v: f"{v:.2f}".rstrip("0").rstrip(".")
    d = [f"M{f(p[0][0])},{f(p[0][1])}"]
    for i in range(n):
        a, b, c, e = p[i - 1], p[i], p[(i + 1) % n], p[(i + 2) % n]
        c1 = (b[0] + (c[0] - a[0]) / 6, b[1] + (c[1] - a[1]) / 6)
        c2 = (c[0] - (e[0] - b[0]) / 6, c[1] - (e[1] - b[1]) / 6)
        d.append(f"C{f(c1[0])},{f(c1[1])} {f(c2[0])},{f(c2[1])} {f(c[0])},{f(c[1])}")
    return " ".join(d) + "Z"


NOTIFICATION_XML = """<?xml version="1.0" encoding="utf-8"?>
<!--
  Statusleisten-Symbol: Silhouette des Klumpens "Nordic Soft", erzeugt von
  Animation/export_nordic_icons.py aus derselben Kontur wie die
  Denk-Animation. Android faerbt es selbst ein, deshalb reines Weiss ohne
  android:tint (sonst sucht aapt2 nach colorControlNormal in den
  App-Themes, was bei reinen Compose-Themes nicht aufgeloest wird).
-->
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="24dp"
    android:height="24dp"
    android:viewportWidth="24"
    android:viewportHeight="24">
    <path
        android:fillColor="#FFFFFFFF"
        android:pathData="{path}" />
</vector>
"""


def main() -> None:
    blob = clean_master()
    written = 0

    radii, off_x, off_y = contour_radii(blob)
    print("Kontur fuer PocketThinkingBlob.kt:", radii, "Versatz", off_x, off_y)
    with open(os.path.join(RES, "drawable", "ic_notification.xml"), "w", encoding="utf-8") as fh:
        fh.write(NOTIFICATION_XML.format(path=blob_path(radii, 24, 1.5)))
    written += 1

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

        # 96dp statt 24dp: Erststart und Leerzustand zeigen das Zeichen in
        # 96dp, ein 24dp-Bild waere dort vierfach hochgezogen und unscharf.
        bm = int(round(96 * factor))
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
    # Homescreen-Symbol fuer iOS/Android-Browser: volle Kachel, das System rundet.
    touch = gradient(180)
    touch.alpha_composite(place(blob, 180, LEGACY_BLOB_OF_TILE))
    touch.convert("RGB").save(WEB_TOUCH)
    written += 1
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
