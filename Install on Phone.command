#!/usr/bin/env bash
# PocketClot — build (if needed) + install + launch on the connected
# Android phone. Double-click in Finder.
#
# Skips the Gradle build when the APK is newer than every source file under
# app/app/src/ — usually finishes in 2-3 seconds.

set -e
cd "$(dirname "$0")"

REPO="$(pwd)"
APP_DIR="$REPO/app"
# Release-APK mit dem registrierten Schluessel CN=joshtech90 (Joscha 24.11.2026).
# Signierdaten: ~/.pocketclot-signing/ (Sicherung im privaten Repo claude-memory).
APK="$APP_DIR/app/build/outputs/apk/release/app-release.apk"
ERWARTET_SHA256="8a47f9f43ce8c4a3b072c2c86bf04f82a8c7919f8070eda55490316e9ee7d2db"

echo "============================================="
echo " PocketClot — Install on Phone"
echo "============================================="

# Pick up Java + Android SDK from the operator's shell profile
export JAVA_HOME="${JAVA_HOME:-/Applications/Android Studio.app/Contents/jbr/Contents/Home}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$PATH"

if [ ! -d "$JAVA_HOME" ]; then
    echo "✗ JAVA_HOME not found at $JAVA_HOME"
    echo "  Install Android Studio or set JAVA_HOME explicitly."
    read -n 1 -s -r -p "Press any key to close…"
    exit 1
fi

if ! command -v adb >/dev/null 2>&1; then
    echo "✗ adb not found on PATH"
    read -n 1 -s -r -p "Press any key to close…"
    exit 1
fi

# Decide whether a build is needed: skip if APK is newer than every source file.
needs_build=true
if [ -f "$APK" ]; then
    newest_src=$(find "$APP_DIR/app/src" "$APP_DIR/app/build.gradle.kts" "$APP_DIR/build.gradle.kts" "$APP_DIR/settings.gradle.kts" \
        -type f -newer "$APK" -print -quit 2>/dev/null || true)
    if [ -z "$newest_src" ]; then
        needs_build=false
    fi
fi

if [ "$needs_build" = true ]; then
    echo "[1/3] Source newer than APK — running Gradle build…"
    cd "$APP_DIR"
    ./gradlew :app:assembleRelease
    cd "$REPO"
else
    echo "[1/3] APK up to date — skipping build."
fi

if [ ! -f "$APK" ]; then
    echo "✗ APK not found at $APK"
    read -n 1 -s -r -p "Press any key to close…"
    exit 1
fi
echo "    APK: $APK ($(du -h "$APK" | cut -f1))"

APKSIGNER=$(ls -d "$ANDROID_HOME"/build-tools/*/apksigner 2>/dev/null | sort -V | tail -1)
if ! "$APKSIGNER" verify --print-certs "$APK" 2>/dev/null | grep -qi "SHA-256 digest: $ERWARTET_SHA256"; then
    echo "✗ APK ist nicht mit dem registrierten Schluessel signiert (fehlt ~/.pocketclot-signing?)."
    read -n 1 -s -r -p "Press any key to close…"
    exit 1
fi
echo "    Signatur: joshtech90 (registriert)"

echo
echo "[2/3] Checking connected devices…"
DEVICES=$(adb devices | sed -e '1d' -e '/^$/d' -e '/offline/d' -e '/unauthorized/d' | wc -l | tr -d ' ')
if [ "$DEVICES" -eq 0 ]; then
    echo "✗ No authorized Android device detected via adb."
    echo "  Plug in the phone, enable USB debugging, confirm the prompt."
    adb devices
    read -n 1 -s -r -p "Press any key to close…"
    exit 1
fi
echo "    $DEVICES device(s) connected"

echo
echo "[3/3] Installing…"
if ! adb install -r "$APK"; then
    echo "✗ Installation abgelehnt. Ist noch die alte Fassung mit anderem Schluessel drauf"
    echo "  (bis v0.6.7 Debug-Schluessel), dann in der App Einstellungen exportieren,"
    echo "  App deinstallieren und dieses Skript erneut starten."
    read -n 1 -s -r -p "Press any key to close…"
    exit 1
fi

# Read package name from the APK and launch the main activity
PKG=$(aapt2 dump packagename "$APK" 2>/dev/null \
   || aapt dump badging "$APK" 2>/dev/null | grep -o "package: name='[^']*'" | head -1 | sed "s/package: name='\([^']*\)'/\1/")
if [ -n "$PKG" ]; then
    echo "    Launching $PKG"
    adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
fi

echo
echo "============================================="
echo " ✓ Done. App is running on the phone."
echo "============================================="
echo
read -n 1 -s -r -p "Press any key to close…"
