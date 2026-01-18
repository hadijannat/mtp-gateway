#!/usr/bin/env sh
set -eu

REPORT_PATH="${MTP_VALIDATION_REPORT_PATH:-}"

if [ -z "$REPORT_PATH" ]; then
  echo "MTP validation report path not set. Set MTP_VALIDATION_REPORT_PATH." >&2
  exit 1
fi

if [ ! -f "$REPORT_PATH" ]; then
  echo "MTP validation report not found: $REPORT_PATH" >&2
  exit 1
fi

if [ ! -s "$REPORT_PATH" ]; then
  echo "MTP validation report is empty: $REPORT_PATH" >&2
  exit 1
fi

echo "MTP validation report found: $REPORT_PATH"
