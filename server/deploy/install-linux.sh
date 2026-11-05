#!/usr/bin/env bash
# =============================================================================
#  PocketClot — Linux One-Shot Installer (Ubuntu/Debian + Fedora/RHEL)
# =============================================================================
#
#  Usage:
#      sudo bash deploy/install-linux.sh
#
#  What it does:
#      1. System packages (python3, venv, curl, nodejs for claude-cli)
#      2. Create service user `pocket-claude`
#      3. Copy repo to /opt/pocket-claude (or update it)
#      4. Create Python venv + install requirements
#      5. Install `claude` CLI via npm (official Anthropic package)
#      6. Generate .env with a random SERVER_TOKEN
#      7. Install systemd service + enable + start
#      8. Print tunnel-setup hint
#
#  Idempotent — can run multiple times, no re-setup needed.
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------- Configuration
INSTALL_DIR="${INSTALL_DIR:-/opt/pocket-claude}"
SERVICE_USER="${SERVICE_USER:-pocket-claude}"
SERVICE_NAME="pocket-claude"
REPO_URL="${REPO_URL:-https://github.com/joshtech90/PocketClot.git}"

# Source directory: either the repo where the script lives (dev path), or
# a fresh clone from GitHub (fresh-install path).
SOURCE_DIR="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)"

# ---------------------------------------------------------------- Pretty-Print
c_blue()   { printf '\033[1;34m%s\033[0m\n' "$*"; }
c_green()  { printf '\033[1;32m%s\033[0m\n' "$*"; }
c_yellow() { printf '\033[1;33m%s\033[0m\n' "$*"; }
c_red()    { printf '\033[1;31m%s\033[0m\n' "$*" >&2; }
step()     { echo; c_blue "==> $*"; }

# ---------------------------------------------------------------- Root-Check
if [[ $EUID -ne 0 ]]; then
    c_red "Please run with sudo: sudo bash $0"
    exit 1
fi

# ---------------------------------------------------------------- OS-Detection
if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    OS_ID="${ID:-unknown}"
    OS_LIKE="${ID_LIKE:-}"
else
    c_red "/etc/os-release not found — unknown OS."
    exit 1
fi

is_debian=false
is_redhat=false
case "$OS_ID $OS_LIKE" in
    *debian*|*ubuntu*) is_debian=true ;;
    *fedora*|*rhel*|*centos*) is_redhat=true ;;
esac

if ! $is_debian && ! $is_redhat; then
    c_yellow "Warning: OS '$OS_ID' is not officially tested. Trying as Debian-like anyway."
    is_debian=true
fi

# ---------------------------------------------------------------- Pre-check: is `claude` already usable?
# If the operator already has a working Claude CLI on PATH (very common —
# many users install it manually before running our installer), we can skip
# the whole Node + npm dance below. Saves install time and avoids version
# collisions with whatever Node version they're already running.
claude_already_present=false
if command -v claude >/dev/null 2>&1; then
    if claude_version_output="$(claude --version 2>&1)" && [[ -n "$claude_version_output" ]]; then
        claude_already_present=true
        c_green "Detected existing Claude CLI: $claude_version_output"
        c_green "Skipping Node.js + npm + claude-cli install."
    fi
fi

# ---------------------------------------------------------------- System packages
step "Installing system packages"
if $is_debian; then
    apt-get update -qq
    apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip \
        curl ca-certificates git poppler-utils
    if ! $claude_already_present; then
        # nodejs/npm separately: if a version is already installed (e.g. via
        # NodeSource), don't overwrite — the NodeSource packages already bundle
        # `npm`, an additional `apt install npm` would collide.
        if ! command -v node >/dev/null 2>&1; then
            apt-get install -y --no-install-recommends nodejs npm
        elif ! command -v npm >/dev/null 2>&1; then
            apt-get install -y --no-install-recommends npm
        fi
    fi
elif $is_redhat; then
    dnf install -y python3 python3-pip python3-virtualenv \
        curl ca-certificates git poppler-utils
    if ! $claude_already_present; then
        if ! command -v node >/dev/null 2>&1; then
            dnf install -y nodejs npm
        elif ! command -v npm >/dev/null 2>&1; then
            dnf install -y npm
        fi
    fi
fi

# Check Node version — claude CLI requires >= 18. Only relevant if we're going
# to install the CLI ourselves; if claude is already on PATH, the operator's
# existing Node setup is by definition fine.
if ! $claude_already_present; then
    node_major="$(node -v 2>/dev/null | sed 's/^v//;s/\..*//' || echo 0)"
    if [[ "$node_major" -lt 18 ]]; then
        c_yellow "Node $node_major is too old (claude CLI requires >=18). Installing NodeSource Node 20..."
        if $is_debian; then
            curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
            apt-get install -y nodejs
        else
            curl -fsSL https://rpm.nodesource.com/setup_20.x | bash -
            dnf install -y nodejs
        fi
    fi
fi

# ---------------------------------------------------------------- Service user
step "Create service user '$SERVICE_USER' (if missing)"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --create-home --shell /bin/bash "$SERVICE_USER"
    c_green "    User created."
else
    c_green "    User already exists."
fi

# ---------------------------------------------------------------- Code deployment
step "Deploying code to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
if [[ -d "$SOURCE_DIR/pocket_claude" ]]; then
    # Local repo (script runs from the source tree): rsync it over.
    c_green "    Local repo detected — copying $SOURCE_DIR -> $INSTALL_DIR"
    # `--exclude .venv` so we don't copy the Mac venv with the wrong binaries.
    # `--exclude data` so a running server doesn't lose its SQLite DB.
    # `--exclude .git` — we don't need repo history on the server.
    rsync -a --delete \
        --exclude '.venv' \
        --exclude 'data' \
        --exclude '.git' \
        --exclude '__pycache__' \
        --exclude '*.pyc' \
        "$SOURCE_DIR/" "$INSTALL_DIR/"
elif command -v git >/dev/null 2>&1; then
    # Fresh install: clone from GitHub.
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        c_green "    Repo exists — pulling"
        git -C "$INSTALL_DIR" pull --ff-only
    else
        c_green "    Cloning repo from $REPO_URL"
        git clone "$REPO_URL" "$INSTALL_DIR"
    fi
else
    c_red "Neither local repo nor git available — cannot deploy."
    exit 1
fi

# Create data/ folder if missing (for fresh install or first start)
mkdir -p "$INSTALL_DIR/data/uploads"

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# ---------------------------------------------------------------- Python venv
step "Python venv + dependencies"
if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
    sudo -u "$SERVICE_USER" python3 -m venv "$INSTALL_DIR/.venv"
fi
sudo -u "$SERVICE_USER" "$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$SERVICE_USER" "$INSTALL_DIR/.venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
c_green "    Dependencies installed."

# ---------------------------------------------------------------- Claude CLI
step "Claude CLI"
if $claude_already_present; then
    c_green "    Re-using existing Claude CLI at $(command -v claude)"
    c_green "    Version: $claude_version_output"
elif command -v claude >/dev/null 2>&1; then
    # Could only happen if claude appeared on PATH between the pre-check and
    # here (very unlikely). Still: don't reinstall.
    c_green "    Claude CLI already present ($(claude --version 2>&1 | head -1))."
else
    npm install -g @anthropic-ai/claude-code
    c_green "    Claude CLI installed."
fi

# Verify the service user can actually run `claude`. The npm-global path
# (/usr/local/bin) is usually on the service user's PATH, but if the operator
# installed Claude into ~/.npm-global or a non-standard prefix, the service
# user won't see it. Surface this immediately rather than at first request.
if ! sudo -u "$SERVICE_USER" -H bash -lc 'command -v claude' >/dev/null 2>&1; then
    c_yellow "Note: 'claude' is on the root PATH but not on the service user's PATH."
    c_yellow "Either move the binary to /usr/local/bin, or set CLAUDE_BINARY in $INSTALL_DIR/.env"
    c_yellow "to its absolute path (e.g. CLAUDE_BINARY=$(command -v claude))."
fi

# ---------------------------------------------------------------- .env
step "Preparing .env file"
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    # Generate a random server token (not directly used for multi-user auth,
    # but pydantic-settings requires a min-length-8 value).
    TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
    sed -i "s|^SERVER_TOKEN=.*|SERVER_TOKEN=$TOKEN|" "$INSTALL_DIR/.env"
    chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.env"
    chmod 600 "$INSTALL_DIR/.env"
    c_green "    Created new .env with a random SERVER_TOKEN."
else
    c_green "    .env already exists — leaving it unchanged."
fi

# ---------------------------------------------------------------- systemd unit
step "Installing systemd service"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
sed -e "s|@PROJECT_DIR@|$INSTALL_DIR|g" -e "s|@SERVICE_USER@|$SERVICE_USER|g" \
    "$INSTALL_DIR/deploy/systemd/pocket-claude.service" > "$SERVICE_FILE"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null
c_green "    Service enabled (starts automatically on boot)."

# ---------------------------------------------------------------- First start
step "Starting server"
# Only start if `claude` is already logged in. Otherwise we end up in a crash
# loop until the operator has run `claude login` as the pocket-claude user.
if sudo -u "$SERVICE_USER" -H bash -c '[[ -f ~/.claude/.credentials.json ]] || [[ -f ~/.claude/credentials.json ]] || [[ -f ~/.config/claude/credentials.json ]]' 2>/dev/null; then
    systemctl restart "$SERVICE_NAME"
    sleep 2
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        c_green "    ✓ Service running."
    else
        c_yellow "    Service not active — see logs: journalctl -u $SERVICE_NAME -n 50"
    fi
else
    c_yellow "    Service NOT YET started — claude login is missing."
fi

# ---------------------------------------------------------------- Next steps
echo
echo "============================================================"
c_green "Base installation complete."
echo "============================================================"
echo
echo "Next steps:"
echo
c_blue "1. Log in to Claude (once per host)"
echo "      sudo -u $SERVICE_USER -H claude login"
echo "   -> opens a URL. Open it on another device, log in,"
echo "      then paste the code back into the terminal."
echo
c_blue "2. Start/restart the server"
echo "      sudo systemctl restart $SERVICE_NAME"
echo "      sudo systemctl status $SERVICE_NAME"
echo
c_blue "3. Set up a tunnel — default path: Tailscale Funnel"
echo "      sudo bash $INSTALL_DIR/deploy/setup-tailscale-funnel.sh"
echo
echo "   -> gives a persistent URL like https://<host>.<tailnet>.ts.net"
echo "   -> free (free tier: 50 GB/month — plenty for a personal chat app)"
echo "   -> no DNS setup, no port forwarding, automatic HTTPS"
echo
echo "   Alternative (power users with their own domain on Cloudflare):"
echo "      sudo bash $INSTALL_DIR/deploy/setup-cloudflare-tunnel.sh"
echo
c_blue "4. Configure the app"
echo "   Enter the server URL from step 3 into the PocketClot app, sign in,"
echo "   done. The initial admin password is in:"
echo "        $INSTALL_DIR/data/INITIAL_PASSWORD.txt"
echo
echo "Tail logs live:    journalctl -u $SERVICE_NAME -f"
echo "Server status:     systemctl status $SERVICE_NAME"
echo
