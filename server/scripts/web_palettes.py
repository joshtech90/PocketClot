#!/usr/bin/env python3
"""Erzeugt die Farbschemata der Web-UI aus den Paletten der Android-App.

Die App ist die Quelle (app/.../ui/theme/ColorSchemes.kt und Color.kt). Dieses
Skript liest dort jede Palette in Hell und Dunkel aus und schreibt sie als
CSS-Variablen nach server/pocket_claude/webui/palettes.css. Aendert sich eine
Palette in der App, reicht ein erneuter Lauf:

    python3 server/scripts/web_palettes.py

Die Zuordnung der Material-Rollen auf die Web-Variablen steht in `tokens()`.
Abweichungen fuer einzelne Paletten stehen in OVERRIDES und sind begruendet.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
THEME = REPO / "app/app/src/main/java/de/smartzone/pocketclaude/ui/theme"
OUT = REPO / "server/pocket_claude/webui/palettes.css"

# Vorgaben wie in der App (SettingsRepository): hell Nordic Blue, dunkel Midnight Atelier.
DEFAULT_LIGHT = "nordic_blue"
DEFAULT_DARK = "midnight_atelier"

# Die App kennt nur Rollen. Wo eine Rolle im Browser nicht passt, steht hier
# der abweichende Wert mit Grund.
OVERRIDES = {
    "chatgpt": {
        # Bei ChatGPT sind Links und Warnungen nicht grau bzw. blau wie die
        # Sekundaer- und Tertiaerrolle der App, sondern Akzent und Bernstein.
        "light": {"link": "#4165E8", "warning": "#A15C00"},
        "dark": {"link": "#8AA6F5", "warning": "#F0B35A"},
    },
}


def _read_sources() -> str:
    return (THEME / "Color.kt").read_text() + "\n" + (THEME / "ColorSchemes.kt").read_text()


def _constants(src: str) -> dict[str, str]:
    consts = {"Color.White": "#FFFFFF", "Color.Black": "#000000"}
    for name, hexv in re.findall(r"val (\w+) = Color\(0x([0-9A-Fa-f]{8})\)", src):
        consts[name] = "#" + hexv[2:].upper()
    # Aliase wie `val NordicLightOnPrimary = Color.White`
    for name, alias in re.findall(r"val (\w+) = (Color\.\w+|[A-Z]\w+)\s*$", src, re.M):
        if alias in consts:
            consts[name] = consts[alias]
    return consts


def _resolve(expr: str, consts: dict[str, str]) -> str:
    expr = expr.strip().rstrip(",")
    m = re.fullmatch(r"Color\(0x([0-9A-Fa-f]{8})\)", expr)
    if m:
        return "#" + m.group(1)[2:].upper()
    if expr in consts:
        return consts[expr]
    raise KeyError(f"Unbekannte Farbe in der App-Palette: {expr}")


def read_palettes() -> dict[str, dict[str, dict[str, str]]]:
    src = _read_sources()
    consts = _constants(src)
    blocks: dict[str, dict[str, str]] = {}
    for m in re.finditer(r"val (\w+) = (?:darkColorScheme|lightColorScheme|PocketColors)\((.*?)\n\)", src, re.S):
        roles: dict[str, str] = {}
        for line in m.group(2).splitlines():
            line = line.split("//")[0].strip()
            mm = re.match(r"(\w+) = (.+)", line)
            if mm:
                roles[mm.group(1)] = _resolve(mm.group(2), consts)
        blocks[m.group(1)] = roles

    ids = dict(re.findall(r"([A-Z_]+)\(\"(\w+)\", \"[^\"]+\"\)", src))
    names = dict(re.findall(r"[A-Z_]+\(\"(\w+)\", \"([^\"]+)\"\)", src))
    palettes: dict[str, dict[str, dict[str, str]]] = {}
    for m in re.finditer(r"val (\w+)Spec = PaletteSpec\((.*?)\)", src, re.S):
        parts = dict(re.findall(r"(\w+) = (\w+)", m.group(2)))
        # MidnightAtelier -> MIDNIGHT_ATELIER -> midnight_atelier
        enum = re.sub(r"(?<!^)(?=[A-Z])", "_", m.group(1)).upper()
        pid = ids.get(enum) or ids.get(enum.replace("CHAT_GPT", "CHATGPT"))
        if not pid:
            raise KeyError(f"Keine Paletten-ID fuer {m.group(1)}")
        palettes[pid] = {
            "name": names[pid],
            "light": {**blocks[parts["lightScheme"]], **{"p_" + k: v for k, v in blocks[parts["lightPocket"]].items()}},
            "dark": {**blocks[parts["darkScheme"]], **{"p_" + k: v for k, v in blocks[parts["darkPocket"]].items()}},
        }
    return palettes


def tokens(c: dict[str, str], dark: bool) -> dict[str, str]:
    """Material-Rollen der App -> Variablen der Web-UI."""
    return {
        "bg": c["background"],
        "sidebar-bg": c["surfaceContainerLowest"] if dark else c["p_surfaceLow"],
        # Menues, Dialoge, Karten: im Dunkeln heller als der Grund, im Hellen weiss.
        "surface": c["surfaceContainerHigh"] if dark else c["surfaceContainerLowest"],
        # Leise Flaechen: Chips, Code-Kopf, Dateikarten.
        "surface-2": c["surfaceContainer"] if dark else c["surfaceVariant"],
        # Eingabefeld wie in der App (ChatComposer: surfaceContainerHigh bzw. Lowest).
        "composer-bg": c["surfaceContainerHigh"] if dark else c["surfaceContainerLowest"],
        "code-bg": c["surfaceContainerLowest"] if dark else c["p_surfaceLow"],
        "border": c["outlineVariant"],
        "border-strong": c["outline"],
        "text": c["onBackground"],
        "text-soft": c["onSurfaceVariant"],
        "bubble-user": c["p_bubbleUser"],
        "bubble-user-fg": c["p_onBubbleUser"],
        "accent": c["primary"],
        "on-accent": c["onPrimary"],
        "selected-bg": c["secondaryContainer"],
        "selected-fg": c["onSecondaryContainer"],
        "link": c["secondary"],
        "danger": c["error"],
        "success": c["p_success"],
        "warning": c["tertiary"],
    }


def _block(selectors: list[str], vals: dict[str, str], dark: bool) -> str:
    body = "\n".join(f"  --{k}: {v};" for k, v in vals.items())
    return ",\n".join(selectors) + " {\n" + body + f"\n  color-scheme: {'dark' if dark else 'light'};\n}}\n"


def render(palettes: dict) -> str:
    out = [
        "/* Farbschemata der Web-UI. GENERIERT von server/scripts/web_palettes.py aus den\n"
        "   Paletten der Android-App (ColorSchemes.kt). Nicht von Hand aendern, sondern\n"
        "   das Skript erneut laufen lassen. */\n",
    ]
    def vals_for(pid: str, mode: str) -> dict[str, str]:
        vals = tokens(palettes[pid][mode], mode == "dark")
        vals.update(OVERRIDES.get(pid, {}).get(mode, {}))
        return vals

    # Zuerst die Vorgaben ohne gewaehlte Palette, in dieser Reihenfolge: bei
    # gleicher Spezifitaet gewinnt der spaetere Block, und [data-theme="dark"]
    # muss :root schlagen.
    out.append(_block([":root", '[data-theme="light"]'], vals_for(DEFAULT_LIGHT, "light"), False))
    out.append(_block(['[data-theme="dark"]'], vals_for(DEFAULT_DARK, "dark"), True))
    for pid in palettes:
        for mode in ("light", "dark"):
            sel = [f'[data-theme="{mode}"][data-palette="{pid}"]']
            out.append(_block(sel, vals_for(pid, mode), mode == "dark"))
    # Ohne JavaScript (oder bevor es laeuft) gilt die Systemeinstellung.
    dark_default = vals_for(DEFAULT_DARK, "dark")
    out.append("@media (prefers-color-scheme: dark) {\n" + "\n".join(
        "  " + line for line in _block([":root:not([data-theme])"], dark_default, True).splitlines()) + "\n}\n")
    return "\n".join(out)


def main() -> None:
    palettes = read_palettes()
    OUT.write_text(render(palettes))
    print(f"{OUT.relative_to(REPO)}: {len(palettes)} Paletten")


if __name__ == "__main__":
    main()
