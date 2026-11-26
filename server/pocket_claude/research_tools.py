"""Read-only research tools shared by the chat engines."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from functools import partial

from pocket_claude import kleinanzeigen_tool


@dataclass(frozen=True)
class ResearchTool:
    name: str
    description: str
    parameters: dict
    skill: str
    configured: Callable[[], bool]
    run: Callable[[dict], Awaitable[dict]]
    matches_url: Callable[[str], bool] | None = None


_DETAIL = ResearchTool(
    name="kleinanzeigen_detail",
    description=(
        "Lies eine öffentliche Kleinanzeigen-Anzeige per Link oder Anzeigen-ID. "
        "Wenn der Nutzer Fotos ansehen oder auswerten lassen will, setze photo_numbers "
        "auf die gewünschten Fotonummern (für das erste Foto [1], höchstens drei pro Antwort). "
        "Das Werkzeug fügt die verfügbaren Fotos als Bilder bei. Beschreibe sichtbare Details "
        "nur anhand dieser Bilder. Leite Maße, Material oder Produktmodelle nur ab, wenn sie "
        "im Bild eindeutig erkennbar sind. Ohne photo_numbers bekommst du Text und Fotolinks. "
        "Berücksichtige den Status und verlinke die Anzeige über url."
    ),
    parameters=kleinanzeigen_tool.DETAIL_PARAMETERS,
    skill="web_fetch",
    configured=kleinanzeigen_tool.configured,
    run=kleinanzeigen_tool.detail,
    matches_url=lambda url: kleinanzeigen_tool.ad_id_from_url(url) is not None,
)

_TOOLS = (
    ResearchTool(
        name="kleinanzeigen_search",
        description=(
            "Suche öffentliche, aktive Angebote direkt auf Kleinanzeigen. Nutze dies "
            "für Kleinanzeigen-Suchen und um Vergleichsangebote für eine Anzeige zu finden. "
            "Die Preise sind Angebotspreise. Verlinke passende Treffer über ihr Feld url."
        ),
        parameters=kleinanzeigen_tool.SEARCH_PARAMETERS,
        skill="web_search",
        configured=kleinanzeigen_tool.configured,
        run=kleinanzeigen_tool.search,
    ),
    _DETAIL,
)


def available(skills: Mapping[str, bool], *, supports_vision: bool = True) -> dict[str, ResearchTool]:
    """Bind the tools and their photo budget to one chat turn."""
    found = {tool.name: tool for tool in _TOOLS if skills.get(tool.skill, True) and tool.configured()}
    if _DETAIL.name in found:
        found[_DETAIL.name] = replace(_DETAIL, run=partial(
            _DETAIL.run, photo_budget=kleinanzeigen_tool.PhotoBudget(), supports_vision=supports_vision,
        ))
    return found


def web_fetch_tools() -> dict[str, ResearchTool]:
    return {tool.name: tool for tool in _TOOLS
            if tool.skill == "web_fetch" and tool.matches_url and tool.configured()}


def for_url(url: str, tools: Mapping[str, ResearchTool]) -> ResearchTool | None:
    return next((tool for tool in tools.values()
                 if tool.skill == "web_fetch" and tool.matches_url and tool.matches_url(url)), None)
