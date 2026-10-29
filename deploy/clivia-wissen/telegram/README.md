# Telegram-Transport fuer ein festes Konto

Diese Kopie gehoert im PocketClaude-Repo nach `deploy/clivia-wissen/telegram/`.
Der Supervisor uebernimmt sie dort; diese Arbeitskopie aendert PocketClaude nicht.
`pocketclot_transport.py` muss bytegleich zu `tools/pocketclot_transport.py` bleiben.
Python 3.10+, cryptography; Mac zusaetzlich Telethon im vorhandenen clivia-venv.
Kein sudo, keine DB, keine Aenderung an den root-Diensten.

## Konfiguration

Nur auf den beteiligten Rechnern, Eigentuemer jeweiliger Benutzer, Modus 0600:

- Mac: `~/.config/clivia/pocketclot-telegram.json`
- Server: `~/.config/clivia/telegram-transport.json`

Pflichtfelder: `chat_id` (negative Gruppen-ID), `user_sender_id`, `bot_sender_id`,
`account` (usr_-Konto), `sign_private` (eigene 32-Byte-Ed25519-Seed Base64),
`peer_public` (32-Byte-Public-Key der Gegenseite Base64).
Server zusaetzlich `bot_token`. Keine IDs/Schluessel im Code oder in Unit-Dateien.
Mac erzeugt den eigenen Signaturschluessel beim einmaligen
`tools/pocketclot_telegram_setup.py`; Setup-Eingabe steht in der 0600-Datei
`pocketclot-telegram-setup.json` mit chat_id, user_sender_id, account,
bot_username und bot_name. Der Setuphelfer schreibt ausschliesslich an den
verifizierten BotFather und veraendert den normalen Nur-Lesen-Helfer nicht.
Bei bereits vorhandenem Ziel legt er keinen weiteren Bot an.
Server erzeugt seinen eigenen Schluessel lokal. Public Keys gegenseitig ueber
bereits authentifizierte SSH-Verbindungen uebernehmen; private Seeds bleiben
jeweils vor Ort. Token nur ueber Pipe in die Serverkonfiguration uebertragen.

Clivias User und der eigene Bot muessen Mitglieder genau dieser Gruppe sein.
Der Bot braucht deaktivierten Privacy-Modus oder Adminrechte. Ein bestehender
Bot darf nicht parallel einen Webhook/anderen getUpdates-Verbraucher haben.

## Einrichten nach Gruppenbeitritt und Review

Auf web als lilith die beiden Python-Dateien nach `~/clivia-telegram/`, die Units
nach `~/.config/systemd/user/` kopieren. Dann:

```sh
systemctl --user daemon-reload
python3 ~/clivia-telegram/server.py
# Erst nach erfolgreichem Erstlauf:
systemctl --user enable --now clivia-telegram.timer
systemctl --user status clivia-telegram.timer --no-pager
```

Mac `pocketclot.json`: eigene `user_id`, `transport: "telegram"`.
Der SSH-Weg bleibt als explizites `transport: "ssh"` erhalten, kein stiller Fallback.
Original-CLI: `abholen`, `chats`, `liefern` (bzw. `alles`) ausfuehren.
`--repo` erlaubt das Testen der neuen Werkzeuge ausserhalb der synchronisierten
Arbeitskopie mit dem echten Wissensordner. Die CLI waehlt bei Telegram selbst
das vorhandene clivia-venv, falls dem aufrufenden Python Telethon fehlt. Dadurch
verwendet auch `wissen_aktuell.py` ohne Aenderung denselben Lieferweg.
LaunchAgent erst nach Endabnahme, weiterhin durch `automatik` und Notaus-Liste.

## Protokoll und Grenzen

Datei = kanonische JSON-Zeile mit signiertem Header, LF, Binaerteil.
Ed25519-Domain: `pocketclot-telegram-v1` plus Nullbyte. Header bindet Version,
Art/Richtung, Konto, UTC-Unixzeit, monotone Transfersequenz, Gesamtlaenge/-Hash,
Teilgroesse/-anzahl/-index und Teilhash/-laenge. Maximal 18 MiB plus 4 KiB Huelle
je Datei, unter dem 20-MB-Bot-Downloadlimit. PCW1 maximal 50 MiB, PCX1 maximal
100 MiB. AES-GCM/PCX1 und deren Kontopruefung bleiben Originalcode.
Gruppen sind keine Telegram-Ende-zu-Ende-Verschluesselung: Nutzdaten sind schon
vor Telegram als PCW1/PCX1 verschluesselt. Signierte PCS1-Statusdateien enthalten
nur Freigabe und Exporthash, keine Chat- oder Wissensinhalte.

Server sendet grosse Exporte nur bei geaendertem SHA-256; alle zehn Minuten
einen signierten Status. Der Mac nimmt ihn nur bis 30 Minuten Alter an und
bindet ihn an den exakt passenden Exporthash. Widerruf ist signierter status
active=false, fehlende/kaputte Exportdatei dagegen ein Fehler. Kein leerer
Ersatzerfolg. Wissen und Status werden nach 24 Stunden abgelehnt; alte verschluesselte
Exportteile bleiben abrufbar, gelten aber nur mit passendem frischem Status.
Erfolgreiche Transfers
setzen erst nach Anwendung die Replaymarke. Teile und Cursor sind persistent,
IO-/Netzfehler lassen die betroffene Nachricht offen. Eine neue oder
beschaedigte Bot-Datei sperrt alte Freigaben dauerhaft bis zum naechsten
gueltigen neuen Status. Vor der Statusbestaetigung liest der Server den Export
nochmals und prueft, dass er seit dem Upload nicht geaendert/entzogen wurde. Maximal acht begonnene
Transfers pro Richtung, alte oder bereits angewendete Teilablagen werden
bereinigt. Nachrichten bleiben in Telegram und werden per Stand uebersprungen.

Nur Nachrichten der konfigurierten Absender in der konfigurierten Gruppe,
keine Weiterleitungen, anonymen Adminbeitraege oder Bot-zu-Bot-Nachrichten.
Der Server liest genau account.export und schreibt genau clivia.paket; er
prueft dafuer die Paketzuordnung in konten.json. Eine falsche innere PCX1-Konto-ID
wird auf dem Mac vor Speichern abgelehnt. Der Server besitzt keine AES-Keys.

Bot-API-Netzwerkcode erlaubt ausschliesslich HTTPS api.telegram.org, keine
Redirects oder Umgebungs-Proxys. Kein Firewallversprechen: diese Beschraenkung
steht im HTTP-Helfer. Mac-Telethon nutzt Telegram-MTProto-Rechenzentren.
Bot-Updates werden von Telegram maximal 24 Stunden gespeichert: nach laengerem
Serverausfall erneut vom Mac liefern; aktuelles PCW1 wird jedes Mal neu gebaut.
Bei komplett verlorenem Mac-Transportzustand werden die weiterhin vorhandenen
Exportdokumente aus der Gruppenhistorie erneut geprueft. Bei lediglich verlorenem
Exportcache entweder den zugehoerigen Mac-Cursor/Empfangsstand zusammen
zuruecklegen oder den Server-Hashstand `sent.json` zuruecklegen, damit der
unveraenderte Export erneut gesendet wird.
Nach mehr als 30 Minuten ohne Status blockiert die Lieferung statt Alt-Freigaben
als aktuell zu bestaetigen. Bereits gespeicherte Pakete bleiben bis zur naechsten
angenommenen Lieferung auf dem Server, wie beim bisherigen SSH-Transport.

Ruecknahme: Timer deaktivieren (`systemctl --user disable --now
clivia-telegram.timer`), Mac-LaunchAgent bootout, Konfigs/Code behalten.
Nicht automatisch auf den bekanntermassen unerreichbaren SSH-Weg wechseln.

## Betrieb ohne Aenderung des synchronisierten Mac-Repos

Solange der Supervisor die Repo-Aenderungen noch nicht zusammengefuehrt hat,
liegt die gepruefte Werkzeugkopie unter `~/.config/clivia/pocketclot-telegram/`.
Dorthin gehoeren pocketclot_lauf.py, pocketclot_wissen.py,
pocketclot_telegram.py, pocketclot_transport.py und der vorhandene telegram.py.
Der LaunchAgent startet `pocketclot_lauf.py alles` ueber `automatik`.

Dieser Lauf liest jedes Mal das aktuelle `~/Projects/Clivia/wissen/`, kopiert
nur Markdown in eine private, temporaere Arbeitskopie unter
`~/.local/state/clivia/pocketclot/arbeitskopien/` und entfernt diese
reproduzierbare Kopie am Ende. Die verwalteten Chat-Notizen stammen nur aus
`~/.local/state/clivia/pocketclot/chatnotizen/`, nie aus moeglichen alten
PocketClot-Ableitungen im Quellrepo. Alle dauerhaften Zustands-/Schluesselpfade
bleiben gleich. Gepruefte Chat-Notizen werden auch nach einem spaeteren
Modell-/Netzfehler gesichert; widerrufene Notizen werden ausserhalb des
Arbeitsbestands wiederherstellbar archiviert. Quellen/Repo bleiben unveraendert.

Fuer den vorhandenen Nachtlauf wird in dessen LaunchAgent nur das Zielprogramm
auf `pocketclot_lauf.py nacht` umgestellt; bisherige Argumente, Zeitplan und
`automatik` bleiben erhalten. Dieser Modus laedt das vorhandene
`wissen_aktuell.py` aus dem Quellrepo und ersetzt nur dessen expliziten
`pocket_run`-Callback durch denselben Laufhelfer. Seine uebrigen Stufen behalten
ihren bisherigen Ablauf. Ein belegter PocketClot-Lock ist ein sichtbarer
Fehler, kein stiller erfolgreicher Skip. Kein globaler Python-Hook, kein
veraendertes sys.executable und keine Aenderung der Repo-Datei notwendig.
Die normalen direkten CLI-Befehle bleiben nach dem Merge verfuegbar;
sie speichern Ableitungen nach bisherigem Verhalten im Repo. Automatik und
Nachtlauf nutzen dagegen weiterhin die externe, geschuetzte Ableitungsablage.

Bei einem Fehler beim Sichern der Notizen bleibt die private Arbeitskopie
unter `arbeitskopien/lauf-*` erhalten. Der naechste Lauf uebernimmt zuerst die
noch vorhandenen Chat-Notizen in die kanonische Ablage. Erst danach wird genau
diese reproduzierbare Kopie entfernt. Eine Kontomarke verhindert die Uebernahme
von Resten eines anderen Kontos. Nicht fertig vorbereitete Kopien werden nie
als leerer Notizbestand uebernommen. Python-Bytecode-Schreiben ist im Laufhelfer
vor dem ersten lokalen Import deaktiviert, auch fuer den importierten Nachtlauf.
