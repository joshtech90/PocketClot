# Daily Workflow

Recommended workflow for continued development of PocketClot after
the initial setup is complete (server running on your mini-PC, app
installed on your phone, your own Tailnet FQDN active).

## What lives where

```
                    Mac (dev machine)             Mini-PC (production)
                    ─────────────────             ──────────────────────
PocketClaude/server  ✏️ code edits                🚀 runs as systemd
  ├─ pocket_claude/  master                       read-only copy
  ├─ deploy/         master                       read-only copy
  ├─ data/           — (Mac server stopped)       📦 data authority
  ├─ .env            — (Mac server stopped)       📦 server token
  └─ .venv           macOS binaries               Linux binaries (separate)

PocketClaude/app     ✏️ code edits                —
  └─ app/build/      APK lands here               —
                    → adb install                 → Android device
```

**Rule:** Data (SQLite DB, uploads, service-account JSON, .env) lives
**only on the mini-PC**. The Mac and the repo stay data-free.

---

## One-time Mac configuration

So the daily deploy knows where to push, add the following to `~/.zshrc`
(or `~/.bashrc`) once:

```bash
export POCKET_CLAUDE_TARGET="me@your-host"                          # SSH target
export POCKET_CLAUDE_PUBLIC_URL="https://your-host.your-tailnet.ts.net"   # public URL
```

Open a new shell and you're ready to go.

---

## Server code update (daily)

When you change a `.py` file:

```
Double-click: Update Mini-PC.command
```

What happens in ~3 seconds:
1. rsync from the Mac repo to `<your-mini-pc>:/opt/pocket-claude/` (code only,
   no data/, no .env, no .venv)
2. If `requirements.txt` changed: `pip install` in the server venv
3. `sudo systemctl restart pocket-claude` (no password prompt thanks to NOPASSWD)
4. Health check via `$POCKET_CLAUDE_PUBLIC_URL/health`

If anything goes wrong, the script prints the last 20 log lines.

### Tail logs in real time
```bash
ssh me@your-host 'sudo -n journalctl -u pocket-claude -f'
```

### Optional Kleinanzeigen research tools

Install a reviewed `kleinanzeigen-cli` build in a dedicated Python environment
on the PocketClot server. The supported command contract is version 0.2.0 from
upstream revision `dfb53f71ce9ab19d1e925fe55dc4d70cb5a730f0`.
Set `KLEINANZEIGEN_CLI_PATH` in the server `.env` to the absolute path of the
installed executable and restart PocketClot. The executable must be accessible
to the service user. Leave the setting empty to disable the tools.

PocketClot uses the CLI's public mobile-API search and ad detail commands with
JSON output. Check both commands from the server before enabling the tools.
PocketClot uses a dedicated state directory under `DATA_DIR`; keep this
installation signed out of Kleinanzeigen. The chat can search, read listing
details and return photo links. The existing Web search and Web fetch switches
control search and ad details respectively.

For another CLI, add a provider module that validates parameters, calls fixed
read-only commands through `pocket_claude/cli_runner.py`, and converts their
JSON to the chat tool result (`ok`, `text`, `sources`). Register its tools in
`pocket_claude/research_tools.py`. Each registration declares its capability
check and the existing web skill it follows. A details tool can also match the
public URLs it handles. Both chat engines use the same registrations.

---

## App code update (daily)

When you change a `.kt` file, connect the Android device via USB:

```bash
cd ~/Projects/PocketClaude/app
./gradlew installDebug && adb shell am start -n de.smartzone.pocketclaude/.MainActivity
```

---

## When should you push to GitHub?

GitHub plays **no role** in the daily loop — the Mac → mini-PC sync runs
directly via rsync, not through `git pull`. But for version tracking and
backup, you should commit regularly:

```bash
cd ~/Projects/PocketClaude
git add -A && git commit -m "…" && git push
```

**Why not a git-based deploy?**
- You'd have to commit + push + ssh + pull after every tiny change →
  ~30 seconds of overhead instead of ~3 seconds
- Local experiments would have to go through the repo first
- The git-pull update path still works as a fallback at any time:
  `ssh me@your-host 'sudo bash /opt/pocket-claude/deploy/helpers/update.sh'`
  — provided the repo was initially deployed via `git clone` (instead of
  rsync). If you need this, run `git clone` once alongside the rsync setup.

---

## Other maintenance actions

### Check server status
```bash
ssh me@your-host 'sudo -n systemctl status pocket-claude'
```

### Tailscale funnel status
```bash
ssh me@your-host 'tailscale funnel status'
```

### Download a backup (DB + uploads)
In the app: *Settings → Back up data → Chat backup → Export* — lands
directly as a ZIP in the Downloads folder of your phone. Encrypted with a
password of your choice.

### Reboot the mini-PC
```bash
ssh me@your-host 'sudo reboot'
```
After 30 seconds everything is back up — systemd handles it. The Tailscale
funnel URL stays the same.

---

## Tools overview

| File | Purpose |
|---|---|
| `Update Mini-PC.command` | Double-click → code + restart, ~3 sec |
| `deploy/push-to-minipc.sh` | What the `.command` calls (handles the systemctl restart) |
| `deploy/install-linux.sh` | First-time setup of a fresh Linux host |
| `deploy/setup-tailscale-funnel.sh` | Set up the tunnel |
| `deploy/migrate-to-server.sh` | One-shot data transfer from old host → new host |
| `deploy/helpers/update.sh` | On the mini-PC: `git pull`-based update (fallback) |
| `deploy/helpers/uninstall.sh` | On the mini-PC: tear everything down |
| `Build & Install PocketClot.command` (app repo) | Push APK to Android device |
| `Find Server URL.command` | Resolve Tailscale URL + copy to clipboard |
| `Deploy to Mini-PC.command` | First-time migration (mostly historical) |

**In the daily loop you'll almost only need `Update Mini-PC.command` and
the app install script.** The rest is setup and emergency tooling.
