#!/usr/bin/env bash
#
# Build the AppImage: a single file that runs on any glibc desktop without installing anything.
#
# Run from the repository root, on the OLDEST distribution you intend to support — an AppImage
# carries everything but glibc, so the build machine's glibc is the floor for every machine that
# runs it. Building on the newest thing to hand is the usual way to ship something that will not
# start on the desktop it was meant for.
#
#     pip install -e ".[package]"
#     ./build/make-appimage.sh
#
# **AppImage rather than Flatpak, and serial access is the reason** (#27). Flatpak has no
# fine-grained serial permission: reaching /dev/ttyUSB0 needs --device=all, which grants every
# device on the machine. An AppImage is not sandboxed, so it inherits the user's own access — the
# same access a checkout has, which is the access this application has always needed. The cost is
# that a udev rule cannot be shipped, so `--doctor` keeps carrying the dialout advice.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
app_id="io.github.tgoodhew.SmartClockMonitor"
dist="$here/dist"
appdir="$dist/AppDir"

version="$(python -c 'import importlib.metadata as m; print(m.version("smartclock-monitor"))')"
echo "Building ${app_id} ${version}"

# 1. The application, as PyInstaller leaves it.
python -m PyInstaller --noconfirm "$here/build/smartclock-monitor.spec"

# 2. The AppDir, which is a filesystem the desktop knows how to read.
rm -rf "$appdir"
mkdir -p "$appdir/usr/bin" \
         "$appdir/usr/share/applications" \
         "$appdir/usr/share/metainfo" \
         "$appdir/usr/share/icons/hicolor/scalable/apps"

cp -a "$dist/smartclock-monitor/." "$appdir/usr/bin/"
cp "$here/packaging/$app_id.desktop"       "$appdir/usr/share/applications/"
cp "$here/packaging/$app_id.metainfo.xml"  "$appdir/usr/share/metainfo/"
cp "$here/packaging/$app_id.svg"           "$appdir/usr/share/icons/hicolor/scalable/apps/"

# appimagetool looks for these three at the AppDir root, by these names.
cp "$here/packaging/$app_id.desktop" "$appdir/$app_id.desktop"
cp "$here/packaging/$app_id.svg"     "$appdir/$app_id.svg"

# 3. AppRun: what the AppImage executes.
cat > "$appdir/AppRun" <<'RUNEOF'
#!/usr/bin/env bash
# Resolve the payload relative to the mounted image rather than the working directory: an AppImage
# is run from wherever the user happens to be, and $0 is the image, not what is inside it.
here="$(dirname "$(readlink -f "$0")")"
export PATH="$here/usr/bin:$PATH"
exec "$here/usr/bin/smartclock-monitor" "$@"
RUNEOF
chmod +x "$appdir/AppRun"

# 4. Wrap it. appimagetool is fetched rather than vendored — it is 10 MB and it is not ours.
tool="$dist/appimagetool"
if [ ! -x "$tool" ]; then
    echo "Fetching appimagetool"
    curl -sSL -o "$tool" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$tool"
fi

ARCH=x86_64 "$tool" "$appdir" "$dist/smartclock-monitor-$version-x86_64.AppImage"

echo
echo "Built: $dist/smartclock-monitor-$version-x86_64.AppImage"
echo "Check it before publishing:  ./dist/smartclock-monitor-*.AppImage --doctor"
