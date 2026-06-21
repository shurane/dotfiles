#!/bin/bash

backup_sync_regex_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//./\\.}"
  value="${value//+/\\+}"
  value="${value//-/\\-}"
  printf '%s' "$value"
}

backup_sync_extension_regex() {
  local exclude_file="$1"
  local line ext escaped
  local -a extensions=()

  while IFS= read -r line; do
    [[ "$line" =~ ^[[:space:]]*($|#) ]] && continue
    if [[ "$line" =~ ^\*\.([[:alnum:]_.+-]+)$ ]]; then
      ext="${BASH_REMATCH[1]}"
      escaped="$(backup_sync_regex_escape "$ext")"
      extensions+=("$escaped")
    fi
  done <"$exclude_file"

  ((${#extensions[@]} > 0)) || return 0

  local IFS='|'
  printf '.*\.(%s)' "${extensions[*]}"
}

backup_sync_summary_patterns() {
  local exclude_file="$1"
  local line

  while IFS= read -r line; do
    [[ "$line" =~ ^[[:space:]]*($|#) ]] && continue
    [[ "$line" == /*/*** ]] || continue
    printf '%s\n' "${line%/***}"
  done <"$exclude_file"
}

backup_sync_write_static_summary() {
  local exclude_file="$1"
  local output_file="$2"
  local path_pattern path

  : >"$output_file"
  while IFS= read -r path_pattern; do
    for path in $path_pattern; do
      [[ -d "$path" ]] || continue
      {
        printf "  %s\n" "$path"
        printf "    size: %s\n" "$(du -shx "$path" 2>/dev/null | awk '{print $1}')"
        printf "    files: %s\n" "$(find "$path" -xdev -type f 2>/dev/null | wc -l)"
        printf "    top-level entries:\n"
        du -xhd1 "$path" 2>/dev/null | sort -h | sed "s/^/      /"
        printf "\n"
      } >>"$output_file"
    done
  done < <(backup_sync_summary_patterns "$exclude_file")
}
