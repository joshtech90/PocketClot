# PocketClot Thinking Blob Animation (Entwurf & Asset-Paket)

> **Stand 22.10.2026: Orange ist abgeloest.** Neues Icon "Nordic Soft"
> (blauer Satin-Klumpen mit 6 Lappen) aus Astras Entwurfsrunde, Denk-Stil
> "Sanftes Atmen" (3,6 s je Zyklus, 97 bis 103 %, +-2 Grad, Morph 12 %).
> Quelle `nordic_soft_master.png`, Export aller App- und Web-Ressourcen mit
> `export_nordic_icons.py`. Kontur und Farben der Denk-Animation in
> `app/.../ui/components/PocketThinkingBlob.kt` sind am Master vermessen.
> Alles unten (Orange, 5 Lappen, 0.8x/20 %) ist History.

Dieses Verzeichnis enthaelt das vollstaendige Design- und Implementierungspaket fuer die animierte, morphende **PocketClot-Masse** waehrend des Denkvorgangs ("Thinking / Streaming").

---

## 🎯 Joschas verifizierte Wunsch-Konfiguration

Die Animation wurde auf folgende Werte abgestimmt und ist in `PocketThinkingBlob.kt` sowie `config.json` als fester Standard hinterlegt:

- **Wobble-Geschwindigkeit:** `0.8x` (`speedMultiplier = 0.8f`)
- **Morph-Intensitaet:** `20%` (`morphIntensity = 0.20f`)
- **Anzahl Lobes / Woelbungen:** `6` (`numLobes = 6`)
- **3D-Glanzpunkt:** `55%` (`specularShine = 0.55f`)
- **Ambient Aura:** Aktiviert (`glowEnabled = true`)

---

## 🎨 Konzept & Dynamik

Das PocketClot-Markenzeichen (die organische, warme 6-lappige Knetmassen-Form) wird waehrend des Denkens lebendig:
1. **Organisches Morphen (20%):** Die 6 Lobes dehnen und entspannen sich dezent und harmonisch ueber $C^1$-stetige Catmull-Rom Bézier-Splines.
2. **Sanftes Atmen:** Die gesamte Masse pulsiert minimal in Groesse (0.95x bis 1.05x) und rotiert subtil (-4 Grad bis +4 Grad).
3. **3D-Knetmassen-Beleuchtung:** Ein wandernder radialer Farbverlauf (Warmgelb `#FDD043` -> Bernstein `#FFB300` -> PocketClot-Orange `#FF6D00` -> Terrakotta `#D84315`) zusammen mit 55% Glanzpunkt-Deckkraft erzeugt ein plastisches Volumen.
4. **Ambient Aura:** Ein weiches Orangelicht im Hintergrund visualisiert die Rechenaktivitaet.

---

## 📁 Enthaltene Dateien

| Datei | Zweck & Format |
|---|---|
| `config.json` | **Maschinenlesbare Konfiguration:** Enthaelt alle Parameter fuer Build-Skripte und LLMs. |
| `PocketThinkingBlob.kt` | **Empfohlene Android-Komponente:** 100% natives Jetpack Compose Canvas mit den voreingestellten Wunsch-Parametern als Default. |
| `preview.html` | **Interaktive Mac-Vorschau:** Physik-Labor und 1:1 Live-Chat-Mockup (oeffnen mit `open Animation/preview.html`). |
| `pocket_clot_thinking.svg` | Standalone Vektor-Animation mit SMIL/CSS-Keyframes. |
| `pocket_clot_thinking.json` | Lottie-Format fuer `com.airbnb.android:lottie-compose`. |
| `original_logo.png` | PNG-Referenz des urspruenglichen statischen Icons mit Defekt. |
| `build_complete_logo_suite.py` | Python-Generator fuer alle 6 reparierten und optimierten Logo- & Icon-Varianten. |
| `icons/` | Vollstaendiges Asset-Paket (Option 1 bis 6) mit Brand Marks, Launcher-Icons, Monochrom-Masken und SVGs. |

---

## 🛠️ Integrationsanleitung fuer das naechste LLM

### Schritt 1: Kotlin-Datei in die App kopieren
Kopiere `Animation/PocketThinkingBlob.kt` nach:
`app/app/src/main/java/de/smartzone/pocketclaude/ui/components/PocketThinkingBlob.kt`

### Schritt 2: In MessageBubble.kt einbinden
In `app/app/src/main/java/de/smartzone/pocketclaude/ui/components/MessageBubble.kt` (Zeile ~239):

```kotlin
// In MessageBubble.kt -> AssistantBubbleHeader:
Row(verticalAlignment = Alignment.CenterVertically) {
    if (text.isEmpty() && isStreaming) {
        // Morphendes Logo waehrend des Denkvorgangs mit Joschas Settings (0.8x, 20%, 6 Lobes, 55% Shine)
        PocketThinkingBlob(
            size = 25.dp,
            isThinking = true,
        )
    } else {
        // Standard-Logo im Ruhezustand
        PocketBrandMark(size = 25.dp)
    }
    Spacer(Modifier.width(8.dp))
    Text(
        text = stringResource(R.string.app_name).uppercase(Locale.ROOT),
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.primary,
    )
}
```

---

## 🖥️ Lokale Vorschau am Mac

```bash
open "/Users/joscha/Projects/PocketClaude/Animation/preview.html"
```
