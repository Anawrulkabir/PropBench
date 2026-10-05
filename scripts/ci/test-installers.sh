#!/usr/bin/env bash
# Unpack or install the installers that `tauri build` produced and run the end-to-end RPC and CLI tests against the
# Python *inside* each one, so CI proves the shipped artifact works, not just the staged resources folder.
# Run from the repository root after `npm run tauri build -- --config src-tauri/tauri.bundle.conf.json`.
set -euo pipefail

bundle=target/release/bundle
work="$PWD/target/installed"
rm -rf "$work"
mkdir -p "$work"

run_tests() {
  local label=$1 python=$2
  echo "::group::E2E + CLI tests against the Python in the $label ($python)"
  if [[ ! -f $python ]]; then
    echo "error: the $label does not contain the bundled Python at $python" >&2
    exit 1
  fi
  PB_WORKER_PYTHON=$python cargo test -p pb-engine --test e2e_property
  PB_WORKER_PYTHON=$python cargo test -p pb-cli
  echo "::endgroup::"
}

only() { # the single file matching a glob, or fail
  local matches=($1)
  if [[ ${#matches[@]} -ne 1 || ! -f ${matches[0]} ]]; then
    echo "error: expected exactly one file matching $1, found: ${matches[*]}" >&2
    exit 1
  fi
  echo "${matches[0]}"
}

case "$(uname -s)" in
  Linux)
    deb=$(only "$bundle/deb/*.deb")
    dpkg-deb -x "$deb" "$work/deb"
    run_tests ".deb" "$work/deb/usr/lib/PropBench/python/bin/python3"

    appimage=$(only "$bundle/appimage/*.AppImage")
    (cd "$work" && APPIMAGE_EXTRACT_AND_RUN=1 "$OLDPWD/$appimage" --appimage-extract >/dev/null)
    run_tests "AppImage" "$work/squashfs-root/usr/lib/PropBench/python/bin/python3"
    ;;
  Darwin)
    dmg=$(only "$bundle/dmg/*.dmg")
    mnt="$work/dmg"
    hdiutil attach -nobrowse -readonly -mountpoint "$mnt" "$dmg"
    trap 'hdiutil detach "$mnt" >/dev/null || true' EXIT
    app="$mnt/PropBench.app"
    codesign --verify --deep --strict --verbose=2 "$app"
    run_tests ".dmg" "$app/Contents/Resources/python/bin/python3"
    ;;
  MINGW* | MSYS* | CYGWIN*)
    setup=$(only "$bundle/nsis/*-setup.exe")
    # Silent per-user install (installMode currentUser): no administrator rights needed. /D must come last.
    # Git Bash would rewrite arguments starting with "/" as paths; switch that off for the NSIS switches.
    MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' "$setup" /S "/D=$(cygpath -w "$work")\\PropBench"
    run_tests "Windows installer" "$work/PropBench/python/python.exe"
    ;;
  *)
    echo "error: unsupported OS $(uname -s)" >&2
    exit 1
    ;;
esac
echo "Installed artifacts verified."
