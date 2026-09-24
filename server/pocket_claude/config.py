"""Settings loaded from .env."""
from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Token-Werte aus den Beispiel-/Doku-Dateien, die NIE als echtes Secret
# durchgehen dürfen — sonst läuft der Server mit einem öffentlich bekannten
# Token im Netz. Startup wird hart abgelehnt, wenn einer davon gesetzt ist.
_PLACEHOLDER_TOKENS = {
    "change-me-to-a-long-random-string",
    "change-me",
    "changeme",
    "your-token-here",
    "secret",
    "token",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Auth (App ↔ Server)
    server_token: str = Field(..., min_length=8)

    # Claude-Agent-SDK nutzt die lokale `claude`-CLI-Installation. Die SDK findet
    # das Binary über PATH oder $CLAUDE_CODE_ENTRYPOINT. Falls Du einen anderen
    # Pfad brauchst, setze ihn unten — wir reichen das an `cli_path` weiter.
    claude_binary: str | None = None
    # Optional: spezifisches Modell überschreiben (sonst SDK-Default)
    claude_model: str | None = None

    # Server
    # Default = loopback. Der Tailscale-Funnel proxyt eh auf localhost:PORT,
    # also reicht 127.0.0.1. Nur wenn der Server bewusst direkt im LAN/VPN
    # erreichbar sein soll, in der .env SERVER_HOST=0.0.0.0 setzen.
    server_host: str = "127.0.0.1"
    server_port: int = 8787
    dev_reload: bool = False

    # CORS: Komma-separierte Liste erlaubter Origins. "*" = alle erlauben
    # (bequem für lokale/Tunnel-Nutzung, heißt aber: jede Website darf die API
    # aufrufen). Für ein engeres Setup CORS_ORIGINS in der .env auf die
    # App-/Web-UI-Origin(s) setzen, z.B. "https://pocket.example.de".
    cors_origins: str = "*"

    # Storage
    data_dir: Path = Path("./data")

    # Uploads
    max_upload_mb: int = 20

    # Context-Warnung in der App: ab wieviel % der 200K Tokens soll der Banner anspringen
    context_warning_ratio: float = 0.85
    max_context_tokens: int = 200_000

    # Logging
    log_level: str = "INFO"

    # ---------- Zusatz-Modelle (Gemini / GPT ueber OpenAI-kompatible Gateways) ----------
    #
    # Claude bleibt das primaere Modell. Wer zusaetzlich Gemini oder GPT im Chat
    # anbieten will, traegt hier die Gateways ein, die auf dem Server erreichbar
    # sind (CLIProxyAPI fuer die Google-Konten, CodexLB fuer die ChatGPT-Konten).
    # Beide sprechen /v1/models und /v1/chat/completions.
    #
    # Variante 1 (empfohlen, beliebig viele Gateways), JSON-Liste:
    #   EXTRA_MODEL_GATEWAYS='[{"id":"pool","label":"Paradies-Pool",
    #     "base_url":"http://127.0.0.1:8317/v1","api_key":"...","timeout":120}]'
    #
    # Variante 2 (Kurzform fuer den Normalfall): die vier Felder darunter.
    # Zeigen beide URLs auf dasselbe Gateway, wird daraus automatisch eins.
    #
    # Alles leer = keine Zusatz-Modelle, die App zeigt nur Claude.
    extra_model_gateways: str = ""
    gemini_gateway_url: str = ""
    gemini_gateway_key: str = ""
    gpt_gateway_url: str = ""
    gpt_gateway_key: str = ""

    # Denktiefe, mit der Zusatz-Modelle laufen, wenn der Client keine mitschickt.
    extra_model_default_effort: str = "high"

    # Kuratierung der Zusatz-Modelle. Ein Gateway meldet alles, was irgendein
    # eingeloggtes Konto kann, und das sind schnell ein Dutzend Varianten
    # ("-agent", "-lite", vier Generationen parallel). Im Picker sollen aber nur
    # die Modelle stehen, die man wirklich benutzen will.
    #
    # Komma-getrennte Glob-Muster auf die BASIS-ID (ohne Denktiefe-Suffix und
    # ohne "gw:<gateway>:"-Praefix), z.B. "gemini-flash,gpt-sol".
    # Leer = keine Filterung, alles wird angeboten.
    #
    # Das Muster "gpt-*" waere zu weit: es liesse auch "gpt-oss-120b" durch, das
    # ueber das Google-Konto laeuft und nichts mit der ChatGPT-Subscription zu
    # tun hat. Deshalb stehen die GPT-Modelle einzeln da. Terra und Reserve
    # bleiben bewusst draussen, die sind fuer die Worker reserviert.
    #
    # Seit 24.09.2026 stehen hier nur Kurznamen ohne Versionsnummer. Der Pool
    # (CLIProxyAPI, `oauth-model-alias`) leitet sie auf die aktuelle Generation
    # um; gesetzt werden sie von `ki-modelle anwenden` im Projekt AI Worker.
    # Eine neue Generation braucht deshalb weder hier noch in der .env etwas.
    model_allowlist: str = "gemini-flash,gpt-sol,gpt-luna"

    # Security: allow the per-chat "Bash" skill at all? Off by default — an
    # app user would otherwise be able to execute arbitrary commands on the
    # host as the `pocket-claude` system user. Operators who explicitly want
    # Bash set ALLOW_BASH=1 in .env.
    allow_bash: bool = False

    @field_validator("server_token")
    @classmethod
    def _reject_placeholder_token(cls, v: str) -> str:
        s = (v or "").strip()
        if s.lower() in _PLACEHOLDER_TOKENS:
            raise ValueError(
                "SERVER_TOKEN ist noch der Beispiel-Platzhalter. Generiere ein "
                "echtes Token: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        raw = (self.cors_origins or "").strip()
        if raw in ("", "*"):
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "pocket_claude.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"


settings = Settings()  # type: ignore[call-arg]
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
