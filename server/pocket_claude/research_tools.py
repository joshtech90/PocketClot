"""Read-only research tools shared by the chat engines."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

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


_TOOLS = (
    ResearchTool(
        name="kleinanzeigen_search",
        description=(
            "Suche öffentliche, aktive Angebote direkt auf Kleinanzeigen. Nutze dies "
            "für Kleinanzeigen-Suchen und um Vergleichsangebote für eine Anzeige zu finden. "
            "Die Preise sind Angebotspreise. Verlinke passende Treffer."
        ),
        parameters=kleinanzeigen_tool.SEARCH_PARAMETERS,
        skill="web_search",
        configured=kleinanzeigen_tool.configured,
        run=kleinanzeigen_tool.search,
    ),
    ResearchTool(
        name="kleinanzeigen_detail",
        description=(
            "Lies eine öffentliche Kleinanzeigen-Anzeige per Link oder Anzeigen-ID. "
            "Verwende dies für Kleinanzeigen-Anzeigenlinks und für Details zu Suchtreffern. "
            "Berücksichtige den Status und verlinke die Anzeige. Fotolinks sind Quellen; "
            "die Bilder wurden nicht angesehen."
        ),
        parameters=kleinanzeigen_tool.DETAIL_PARAMETERS,
        skill="web_fetch",
        configured=kleinanzeigen_tool.configured,
        run=kleinanzeigen_tool.detail,
        matches_url=lambda url: kleinanzeigen_tool.ad_id_from_url(url) is not None,
    ),
)


def available(skills: Mapping[str, bool]) -> dict[str, ResearchTool]:
    return {tool.name: tool for tool in _TOOLS if skills.get(tool.skill, True) and tool.configured()}


def for_url(url: str, tools: Mapping[str, ResearchTool]) -> ResearchTool | None:
    return next((tool for tool in tools.values() if tool.matches_url and tool.matches_url(url)), None)
