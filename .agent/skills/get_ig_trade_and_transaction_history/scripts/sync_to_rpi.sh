#!/bin/bash

# Load configuration from .env if it exists
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

DESTINATION="${SYNC_DESTINATION}"
if [ -z "$DESTINATION" ]; then
    echo "Error: SYNC_DESTINATION not set in .env"
    exit 1
fi

# Set default downloads dir or read from .env if defined there
DOWNLOADS_DIR="${DOWNLOAD_DIR:-$HOME/Downloads}"

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --download-dir) DOWNLOADS_DIR="$2"; shift ;;
        -h|--help) 
            echo "Usage: $0 [--download-dir <path>]"
            exit 0
            ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

FILES_TO_SYNC=()

# Find the latest Trade and Transaction history files
LATEST_TRADE=$(ls -t "$DOWNLOADS_DIR"/TradeHistory-*.csv 2>/dev/null | head -n 1)
LATEST_TRANS=$(ls -t "$DOWNLOADS_DIR"/TransactionHistory-*.csv 2>/dev/null | head -n 1)

if [ -n "$LATEST_TRADE" ]; then
    FILES_TO_SYNC+=("$LATEST_TRADE")
fi

if [ -n "$LATEST_TRANS" ]; then
    FILES_TO_SYNC+=("$LATEST_TRANS")
fi

if [ ${#FILES_TO_SYNC[@]} -eq 0 ]; then
    echo "No IG history files found in $DOWNLOADS_DIR"
    exit 1
fi

echo "Syncing files to $DESTINATION..."
for FILE in "${FILES_TO_SYNC[@]}"; do
    echo "Transferring: $(basename "$FILE")"
    # Quote the source and destination properly
    scp "$FILE" "$DESTINATION"
done

if [ $? -eq 0 ]; then
    echo "Sync complete!"
else
    echo "Sync failed."
    exit 1
fi
