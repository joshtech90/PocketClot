# Clivias PocketClot-Gedaechtnis vorbereiten und installieren

Dieses Paket installiert ausschliesslich die zwei geprueften Servermodule und
kontogebundene Wissenstransporte. Kein Patch auf dem Server, keine Automatik,
keine Aenderung an Datenbank, WebUI oder bestehenden Wissenspaketen.

## Upload bauen und einmal sudo ausfuehren

Voraussetzungen: Python 3 mit cryptography auf web, sqlite3 mit -readonly/-json,
aktiver systemd-Dienst pocket-claude, Deploy unter /opt/pocket-claude,
SSH-Transportnutzer lilith. Die beiden Servermodule muessen entweder dem
geprueften Ausgangsstand oder den mitgelieferten Repo-Dateien entsprechen.
Bei zwischenzeitlichen Serveraenderungen bricht das Skript vor Aenderungen ab.

In `deploy/clivia-wissen/upload/` liegen ausschliesslich diese oeffentlichen
Parameter. Sie bleiben gitignored, da das Repo oeffentlich ist:

- `liefern.pub`: Clivias oeffentlicher Ed25519-Lieferschluessel
- `abholen.pub`: davon verschiedener oeffentlicher Ed25519-Abholschluessel
- `export.pub`: oeffentlicher X25519-Empfaenger, base64url
- `from-ip.txt`: Clivias stabile Tailscale-IPv4 fuer SSH from=

Im Repo:

```sh
python3 deploy/clivia-wissen/vorbereiten.py
scp -r .ai/tmp/clivia-wissen-upload web:clivia-wissen-upload
ssh -t web 'cd ~/clivia-wissen-upload && sudo bash einrichten.sh'
```

`vorbereiten.py` nimmt `wissen_export.py` und `wissen_tool.py` direkt aus
`server/pocket_claude/`. Der Upload enthaelt diese vollstaendigen Module,
keine lose Patchdatei. Der konkrete Laufbericht nennt Arbeitskopie und
Befehle, damit nicht versehentlich eine andere Arbeitskopie verwendet wird.
Das Paket hier nicht live ausfuehren, bevor die lokale Pruefung abgeschlossen ist.

## Was die Einrichtung sichert und prueft

`einrichten.sh` und `zuruecknehmen.sh` verwenden `set -euo pipefail`. Die
Transaktion in `installation.py` sperrt parallele Installationen. Sie ermittelt
Clivias ID mit `sqlite3 -readonly` anhand `lower(name) = 'clivia'` und bricht
bei null oder mehreren Treffern ab. Es werden nur ID und Name abgefragt.
Joscha/Kati werden anhand der bestehenden eindeutigen Paketbindungen
`wissen.paket`/`kati.paket` bestimmt, ohne ihre Freigaben zu erweitern.

Vor dem Stoppen des Diensts werden alle sechs Zieldateien unter
`/var/backups/pocketclot-clivia/<Zeitstempel>-<Zufall>/` gesichert:
`authorized_keys`, `konten.json`, die beiden Servermodule und die zwei neuen
Transportskripte, sofern schon vorhanden. Das Manifest vermerkt vorheriges
Fehlen, Hashes, Eigentuemer und Dateirechte. Die Backupablage ist 0700.

Die aihub-Abholzeile behaelt Public-Key und from=-Beschraenkung. Ihr neuer
Zwangsbefehl bekommt ausschliesslich die zwei bisherigen Konto-IDs. Doppelte
Verwendung desselben Keys oder weitere alte Abholzeilen fuehren zum Abbruch.
Clivias zwei Keys erhalten je einen festen Zwangsbefehl, `restrict` und ihr
`from=`. `SSH_ORIGINAL_COMMAND` und Clientargumente bestimmen niemals Konto
oder Paketname. Die Lieferung akzeptiert nur `clivia.paket`.

`konten.json` wird zusammengefuehrt. Alle bestehenden Konten, unbekannten
Felder und der globale Exportempfaenger bleiben erhalten. Clivia bekommt einen
eigenen Empfaenger. Ein abweichender vorhandener Clivia-Eintrag wird nicht
ueberschrieben. Der Dienst wird neu gestartet, mit `is-active` und bis zu
30 Bereitschaftsversuchen ueber
`http://127.0.0.1:8787/health` (`status=ok`, `db_ok=true`) geprueft.
Bei einem Fehler nach Sicherung werden die gesicherten Dateien zurueckgespielt
und der Dienst erneut gestartet. Scheitert auch dies, nennt die Ausgabe den
Backupordner, die Einrichtung bleibt fehlgeschlagen.

## Mac-Vorbereitung und Erstlauf

Die Mac-Helfer werden nur unter `~/.config/clivia/` installiert. Sie benutzen
`~/Projects/Clivia/tools/pocketclot_wissen.py`, keine zweite Kopie der Pipeline.
`mac-vorbereiten.py <Web-Tailscale-IP> '<verifizierter Ed25519-Hostkey>'` erzeugt
nur fehlende Schluessel und baut ein lokales Paket. Private Dateien verlassen
den Mac nicht. Der Server-Hostkey kommt aus der bestehenden Supervisor-SSH-
Verbindung, kein blindes ssh-keyscan. Die eigene known_hosts-Datei liegt im
freigegebenen Konfigurationsordner. Eigene SSH-Konfiguration, nur jeweiliger
Transportkey, StrictHostKeyChecking=yes.

Da die Datenbank erst beim sudo-Schritt lesbar ist, enthaelt die vorbereitete
Mac-Konfiguration `user_id: null`. Der native Abhol-/Lieferaufruf ist damit
absichtlich noch nicht moeglich. Beim lokalen Paketbau wird intern ein
syntaktischer Vorbereitungsidentifier verwendet; das PCW1-Wissenspaket hat
keine Konto-ID, und es werden dabei keine Chats abgeholt oder verarbeitet.

Nach erfolgreicher Serverinstallation, auf dem Mac:

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3 ~/.config/clivia/pocketclot-erstlauf.py
```

Dieser Helfer uebernimmt aus dem authentifizierten, kontogebundenen Transport
genau eine Konto-ID, lehnt Kontowechsel ab, wartet maximal zwei Minuten auf
den ersten Export und fuehrt unter durchgehender Laufsperre nacheinander die
Originalfunktionen `abholen`, `chats`, `liefern` aus. Eine belegte Sperre ist
ein Fehler, kein stiller Erfolg. Fehler stoppen die Folge. Danach koennen
diese drei
Befehle auch direkt in `~/Projects/Clivia` aufgerufen werden. Fuer eine
Wiederholungsprobe muss `chats` null geaenderte Chats melden.

Der AES-Schluessel muss zusaetzlich lokal im jeweiligen Client unter
Einstellungen > Gedaechtnis stehen. Er darf weder auf web noch in Bericht,
Chat, Upload oder Git landen. Vor Automatik lokale Quellen-/Zitatstichprobe
und echte Suchprobe im Client durchfuehren. Es wird kein LaunchAgent angelegt.
Der Serverexport beginnt etwa 90 Sekunden nach Dienststart, danach stuendlich.

## Kompatibilitaet und lokale Pruefung

Abholung bleibt JSON mit `freigegeben` und `exporte` aus `konto`/Base64-`daten`.
Freigegeben ohne Export bedeutet eine Exportluecke, kein Widerruf. Defekte
Kontenlisten sind Fehler. Das Gesamtlimit von 110 MiB Rohdaten laesst Platz
fuer Base64/JSON unter dem 150-MiB-Limit von `wissen_kati.py`.
Leben wird nicht geaendert. Der synthetische Test kompiliert die unveraenderten
Originalfunktionen aus Leben und prueft echte PCX1-Entschluesselung, Trennung,
Exportluecke und Widerruf einschliesslich Cache. Ohne die optionale externe
Quelle wird dieser Integrationstest ausdruecklich uebersprungen.

```sh
mkdir -p .ai/tmp
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.ai/tmp" PYTHONPATH=server \
  python3 -m pytest -q -p no:cacheprovider --basetemp=.ai/tmp/pytest-clivia server/tests
```

Die Tests bauen einen eigenen Verzeichnisbaum, synthetische SQLite-Datenbank,
Testkeys und systemctl-Ersatz. `CLIVIA_TEST_ROOT` lenkt ALLE Server-Zielpfade
um. Die Testwurzel braucht `.clivia-test-root` mit `Nur lokale Tests`; `/`
ist nicht als Testwurzel erlaubt. Es gibt keinen Produktions-Trockenlauf,
der doch heimlich einen Dienst startet. Im echten Betrieb darf die Variable
nicht gesetzt sein. Geprueft: Wiederholung, Merge, Sicherung, exakte Ruecknahme,
Neustart-/Statusfehler, mehrdeutiges Konto, Schluesselkollision und Symlinks.

## Ruecknahme

Mit dem von der Einrichtung ausgegebenen Backupordner, auf web:

```sh
cd ~/clivia-wissen-upload
sudo bash zuruecknehmen.sh /var/backups/pocketclot-clivia/ZEITSTEMPEL-ZUFALL
```

Die Ruecknahme prueft Backuphashes und lehnt seit der Installation veraenderte
Dateien ab. Sie entfernt zuerst Clivias Kontofreigabe, bevor die alte breite
Abholzeile wiederhergestellt wird. Neue Transportskripte werden nur dann
entfernt, wenn sie vor der Installation nicht existierten. Bestehende Pakete,
Datenbank, Exporte und Mac-Schluessel bleiben erhalten. Es wird kein Ordner
rekursiv geloescht. Backups bleiben zur Nachpruefung liegen.
