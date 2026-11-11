#!/usr/bin/env bash
# Compile with warnings + sanitizers and run against input.txt next to the source.
# Usage: scripts/run.sh practice/900/1807D_odd_queries.cpp [input-file]
set -euo pipefail
src="${1:?usage: scripts/run.sh file.cpp [input]}"
dir="$(dirname "$src")"
input="${2:-$dir/input.txt}"
g++ -std=c++17 -O2 -Wall -Wextra -Wshadow -fsanitize=address,undefined -o "$dir/main" "$src"
if [ -f "$input" ]; then
  "$dir/main" < "$input"
else
  "$dir/main"
fi
