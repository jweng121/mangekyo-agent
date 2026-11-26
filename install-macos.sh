#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    printf 'Usage: bash install-macos.sh PATH_TO_MANGEKYO [EXPECTED_SHA256]\n' >&2
    exit 2
fi

source_binary=$1
if [[ ! -f $source_binary ]]; then
    printf 'Mangekyo executable not found: %s\n' "$source_binary" >&2
    exit 1
fi
source_binary=$(cd "$(dirname "$source_binary")" && pwd)/$(basename "$source_binary")
if [[ $# -eq 2 ]]; then
    actual_hash=$(shasum -a 256 "$source_binary")
    actual_hash=${actual_hash%% *}
    if [[ $actual_hash != "$2" ]]; then
        printf 'Mangekyo SHA256 mismatch; existing installation was left intact.\n' >&2
        exit 1
    fi
fi

install_dir=${MANGEKYO_BIN_DIR:-${XDG_BIN_HOME:-$HOME/.local/bin}}
mkdir -p "$install_dir"
install_dir=$(cd "$install_dir" && pwd)
staged=$(mktemp "$install_dir/.mangekyo.XXXXXXXX")
trap 'rm -f "$staged"' EXIT
install -m 755 "$source_binary" "$staged"
"$staged" setup
mv -f "$staged" "$install_dir/mangekyo"
trap - EXIT

printf 'Installed Mangekyo: %s\n' "$install_dir/mangekyo"
case ":$PATH:" in
    *":$install_dir:"*) ;;
    *) printf 'Add this directory to PATH in your shell profile: %s\n' "$install_dir" ;;
esac
