#!/bin/bash
set -euo pipefail
shopt -s nullglob

BASE_EXCLUDES=/etc/backup-sync-excludes
MAX_FILE_SIZE="+500M"
REPORT_HOME=/home/pi
REPORT_DIR="$REPORT_HOME/.rpi-clone"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=backup-sync-lib.sh
source "$SCRIPT_DIR/backup-sync-lib.sh"

runtime_excludes=""
skipped_report=""
synced_report=""
dynamic_skips=""
static_summary=""
extension_regex=""
clone_mounted=0
start_epoch="$(date +%s)"

format_duration() {
  local seconds="$1"
  printf "%02d:%02d:%02d" "$((seconds / 3600))" "$(((seconds % 3600) / 60))" "$((seconds % 60))"
}

log() {
  printf "%s %s\n" "$(date --iso-8601=seconds)" "$*"
}

cleanup() {
  if [[ "$clone_mounted" == "1" ]]; then
    umount /mnt/clone 2>/dev/null || true
  fi
  rm -f "$runtime_excludes" "$skipped_report" "$synced_report" "$dynamic_skips" "$static_summary"
}
trap cleanup EXIT

root_source="$(findmnt -n -o SOURCE /)"
boot_source="$(findmnt -n -o SOURCE /boot/firmware)"

if [[ "$root_source" != "/dev/sda2" ]]; then
  log "Refusing to sync: / is mounted from $root_source, expected /dev/sda2"
  exit 1
fi

if [[ "$boot_source" != "/dev/sda1" ]]; then
  log "Refusing to sync: /boot/firmware is mounted from $boot_source, expected /dev/sda1"
  exit 1
fi

if [[ ! -b /dev/mmcblk0 || ! -b /dev/mmcblk0p2 ]]; then
  log "Refusing to sync: SD card target /dev/mmcblk0p2 is missing"
  exit 1
fi

if mountpoint -q /mnt/clone; then
  log "Refusing to sync: /mnt/clone is already mounted"
  exit 1
fi

if [[ ! -r "$BASE_EXCLUDES" ]]; then
  log "Refusing to sync: missing readable exclude file $BASE_EXCLUDES"
  exit 1
fi

runtime_excludes="$(mktemp /tmp/backup-sync-excludes.XXXXXX)"
skipped_report="$(mktemp /tmp/backup-sync-skipped.XXXXXX)"
synced_report="$(mktemp /tmp/backup-sync-synced.XXXXXX)"
dynamic_skips="$(mktemp /tmp/backup-sync-dynamic.XXXXXX)"
static_summary="$(mktemp /tmp/backup-sync-static-summary.XXXXXX)"

cat "$BASE_EXCLUDES" >"$runtime_excludes"

timestamp="$(date +%Y%m%d-%H%M%S)"
skipped_report_name="$timestamp.skipped.txt"
synced_report_name="$timestamp.synced.txt"

extension_regex="$(backup_sync_extension_regex "$BASE_EXCLUDES")"

if [[ -n "$extension_regex" ]]; then
  find / -xdev \
    \( -path /dev -o -path /proc -o -path /run -o -path /sys -o -path /tmp -o -path /mnt -o -path /media \) -prune \
    -o -type f \( -size "$MAX_FILE_SIZE" -o -iregex "$extension_regex" \) -printf "/%P\n" \
    | sort -u >"$dynamic_skips"
else
  find / -xdev \
    \( -path /dev -o -path /proc -o -path /run -o -path /sys -o -path /tmp -o -path /mnt -o -path /media \) -prune \
    -o -type f -size "$MAX_FILE_SIZE" -printf "/%P\n" \
    | sort -u >"$dynamic_skips"
fi
cat "$dynamic_skips" >>"$runtime_excludes"

backup_sync_write_static_summary "$BASE_EXCLUDES" "$static_summary"

{
  printf "backup-sync skipped file report\n"
  printf "timestamp: %s\n" "$(date --iso-8601=seconds)"
  printf "started: %s\n" "$(date --date="@$start_epoch" --iso-8601=seconds)"
  printf "source root: %s\n" "$root_source"
  printf "destination root: /dev/mmcblk0p2\n"
  printf "max file size filter: %s\n" "$MAX_FILE_SIZE"
  printf "\nStatic exclude patterns from %s:\n" "$BASE_EXCLUDES"
  sed "s/^/  /" "$BASE_EXCLUDES"
  printf "\nConcrete dynamic skipped files: large files and media/disk images:\n"
  sed "s/^/  /" "$dynamic_skips"
  printf "\nStatic excluded directory summaries:\n"
  cat "$static_summary"
} >"$skipped_report"

{
  printf "backup-sync synced file report\n"
  printf "timestamp: %s\n" "$(date --iso-8601=seconds)"
  printf "started: %s\n" "$(date --date="@$start_epoch" --iso-8601=seconds)"
  printf "source root: %s\n" "$root_source"
  printf "destination root: /dev/mmcblk0p2\n"
  printf "\nVerbose rpi-clone output from the real sync:\n"
} >"$synced_report"

exclude_count="$(grep -vc "^\s*\(#\|$\)" "$runtime_excludes" || true)"
dynamic_count="$(grep -c "^/" "$dynamic_skips" || true)"
static_count="$(grep -c "^  /" "$static_summary" || true)"
log "Starting SSD-to-SD fallback sync with rpi-clone using $exclude_count exclude patterns; $dynamic_count dynamic skips; $static_count static excluded dirs summarized"

flock -n /run/backup-sync.lock /usr/local/sbin/rpi-clone -v -u --exclude-from="$runtime_excludes" mmcblk0 2>&1 \
  | tee -a "$synced_report"

end_epoch="$(date +%s)"
elapsed_seconds="$((end_epoch - start_epoch))"
elapsed_hms="$(format_duration "$elapsed_seconds")"

{
  printf "\nfinished: %s\n" "$(date --date="@$end_epoch" --iso-8601=seconds)"
  printf "elapsed seconds: %s\n" "$elapsed_seconds"
  printf "elapsed: %s\n" "$elapsed_hms"
} >>"$skipped_report"

{
  printf "\nfinished: %s\n" "$(date --date="@$end_epoch" --iso-8601=seconds)"
  printf "elapsed seconds: %s\n" "$elapsed_seconds"
  printf "elapsed: %s\n" "$elapsed_hms"
} >>"$synced_report"

log "Writing reports locally: $REPORT_DIR/$skipped_report_name and $REPORT_DIR/$synced_report_name"
mkdir -p "$REPORT_DIR"
install -m 0644 "$skipped_report" "$REPORT_DIR/$skipped_report_name"
install -m 0644 "$synced_report" "$REPORT_DIR/$synced_report_name"
chown --reference="$REPORT_HOME" "$REPORT_DIR" "$REPORT_DIR/$skipped_report_name" "$REPORT_DIR/$synced_report_name" 2>/dev/null || true

log "Writing reports to SD fallback: $REPORT_DIR/$skipped_report_name and $REPORT_DIR/$synced_report_name"
mkdir -p /mnt/clone
mount /dev/mmcblk0p2 /mnt/clone
clone_mounted=1
mkdir -p "/mnt/clone$REPORT_DIR"
install -m 0644 "$skipped_report" "/mnt/clone$REPORT_DIR/$skipped_report_name"
install -m 0644 "$synced_report" "/mnt/clone$REPORT_DIR/$synced_report_name"
chown --reference="/mnt/clone$REPORT_HOME" \
  "/mnt/clone$REPORT_DIR" \
  "/mnt/clone$REPORT_DIR/$skipped_report_name" \
  "/mnt/clone$REPORT_DIR/$synced_report_name" \
  2>/dev/null || true

sync "$REPORT_DIR/$skipped_report_name" "$REPORT_DIR/$synced_report_name" "/mnt/clone$REPORT_DIR/$skipped_report_name" "/mnt/clone$REPORT_DIR/$synced_report_name"
umount /mnt/clone
clone_mounted=0

log "SSD-to-SD fallback sync completed in $elapsed_hms ($elapsed_seconds seconds)"
