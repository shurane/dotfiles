#!/usr/bin/env bash
set -e

# ==============================================================================
# Jellyfin Hardware Acceleration Detection & Configuration
#
# Usage:
# 1. Container Entrypoint (passes through to command):
#    /detect-settings.sh /jellyfin/jellyfin
#
# 2. Host CLI Diagnostic:
#    ./detect-settings.sh --detect   -> prints detected accelerator (qsv|vaapi|none)
#    ./detect-settings.sh --env      -> prints host GIDs and recommended env vars
#    ./detect-settings.sh --info     -> prints detailed human-readable GPU diagnostics
# ==============================================================================

detect_gpu() {
    local vendor_file="/sys/class/drm/renderD128/device/vendor"
    if [ -f "$vendor_file" ]; then
        local vendor
        vendor=$(cat "$vendor_file" 2>/dev/null || true)
        case "$vendor" in
            "0x8086") echo "qsv" ;;
            "0x10de") echo "nvenc" ;;
            "0x1002") echo "vaapi" ;;
            *)        echo "vaapi" ;;
        esac
    else
        echo "none"
    fi
}

# --- Host-side Diagnostic Modes ---
if [ "$1" = "--detect" ] || [ "$1" = "-d" ]; then
    detect_gpu
    exit 0
fi

if [ "$1" = "--env" ]; then
    ACCEL=$(detect_gpu)
    RENDER_GID=$(stat -c '%g' /dev/dri/renderD128 2>/dev/null || echo "none")
    VIDEO_GID=$(stat -c '%g' /dev/dri/card0 2>/dev/null || echo "none")
    echo "JELLYFIN_HW_ACCEL=$ACCEL"
    echo "RENDER_GID=$RENDER_GID"
    echo "VIDEO_GID=$VIDEO_GID"
    exit 0
fi

if [ "$1" = "--info" ]; then
    ACCEL=$(detect_gpu)
    echo "=== GPU Diagnostic Info ==="
    echo "Device: /dev/dri/renderD128"
    if [ -e /dev/dri/renderD128 ]; then
        VENDOR=$(cat /sys/class/drm/renderD128/device/vendor 2>/dev/null || echo "unknown")
        RENDER_GID=$(stat -c '%g' /dev/dri/renderD128 2>/dev/null || echo "unknown")
        echo "Vendor ID:     $VENDOR"
        echo "Render GID:    $RENDER_GID"
        echo "Target Accel:  $ACCEL"
    else
        echo "No /dev/dri/renderD128 found."
        echo "Target Accel:  none"
    fi
    exit 0
fi

# --- Container Auto-Detection & Configuration Mode ---
CONFIG="/config/config/encoding.xml"
ACCEL=$(detect_gpu)

echo "[detect-settings] Detecting hardware capabilities..."

if [ "$ACCEL" = "qsv" ]; then
    echo "[detect-settings] Intel GPU detected (vendor 0x8086). Ensuring QuickSync (QSV) is configured..."
    if [ -f "$CONFIG" ]; then
        # Ensure hardware acceleration type is qsv
        sed -i 's|<HardwareAccelerationType>.*</HardwareAccelerationType>|<HardwareAccelerationType>qsv</HardwareAccelerationType>|g' "$CONFIG"
        # Ensure hardware tone-mapping is enabled
        sed -i 's|<EnableTonemapping>.*</EnableTonemapping>|<EnableTonemapping>true</EnableTonemapping>|g' "$CONFIG"
        sed -i 's|<EnableVppTonemapping>.*</EnableVppTonemapping>|<EnableVppTonemapping>true</EnableVppTonemapping>|g' "$CONFIG"
        # Ensure throttling is enabled (prevents runaway CPU on unbuffered encodes)
        sed -i 's|<EnableThrottling>.*</EnableThrottling>|<EnableThrottling>true</EnableThrottling>|g' "$CONFIG"
        # Ensure Intel low power encoders are enabled
        sed -i 's|<EnableIntelLowPowerH264HwEncoder>.*</EnableIntelLowPowerH264HwEncoder>|<EnableIntelLowPowerH264HwEncoder>true</EnableIntelLowPowerH264HwEncoder>|g' "$CONFIG"
        sed -i 's|<EnableIntelLowPowerHevcHwEncoder>.*</EnableIntelLowPowerHevcHwEncoder>|<EnableIntelLowPowerHevcHwEncoder>true</EnableIntelLowPowerHevcHwEncoder>|g' "$CONFIG"
    fi
elif [ "$ACCEL" = "vaapi" ]; then
    echo "[detect-settings] AMD/generic GPU detected. Ensuring VAAPI is configured..."
    if [ -f "$CONFIG" ]; then
        sed -i 's|<HardwareAccelerationType>.*</HardwareAccelerationType>|<HardwareAccelerationType>vaapi</HardwareAccelerationType>|g' "$CONFIG"
        sed -i 's|<EnableTonemapping>.*</EnableTonemapping>|<EnableTonemapping>true</EnableTonemapping>|g' "$CONFIG"
        sed -i 's|<EnableVppTonemapping>.*</EnableVppTonemapping>|<EnableVppTonemapping>true</EnableVppTonemapping>|g' "$CONFIG"
        sed -i 's|<EnableThrottling>.*</EnableThrottling>|<EnableThrottling>true</EnableThrottling>|g' "$CONFIG"
    fi
else
    echo "[detect-settings] No supported GPU acceleration found. Running in standard mode."
fi

# Execute whatever command was passed from docker-compose.yml
echo "[detect-settings] Launching: $@"
exec "$@"
