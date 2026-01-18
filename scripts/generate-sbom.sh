#!/usr/bin/env bash
# Generate Software Bill of Materials (SBOM) in CycloneDX format
# Requires: pip install cyclonedx-bom
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="${1:-$PROJECT_ROOT/sbom}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Check for cyclonedx-py
if ! command -v cyclonedx-py &> /dev/null; then
    warn "cyclonedx-py not found. Installing..."
    pip install cyclonedx-bom
fi

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Get version from git or package
VERSION=$(python -c "from mtp_gateway import __version__; print(__version__)" 2>/dev/null || echo "unknown")
TIMESTAMP=$(date -u +"%Y%m%d-%H%M%S")

info "Generating SBOM for mtp-gateway v${VERSION}"
info "Output directory: $OUTPUT_DIR"

# Generate SBOM from current environment
info "Generating environment SBOM (JSON)..."
cyclonedx-py environment \
    --output "$OUTPUT_DIR/sbom-${VERSION}-${TIMESTAMP}.json" \
    --format json \
    --schema-version 1.5

info "Generating environment SBOM (XML)..."
cyclonedx-py environment \
    --output "$OUTPUT_DIR/sbom-${VERSION}-${TIMESTAMP}.xml" \
    --format xml \
    --schema-version 1.5

# Create latest symlinks
ln -sf "sbom-${VERSION}-${TIMESTAMP}.json" "$OUTPUT_DIR/sbom-latest.json"
ln -sf "sbom-${VERSION}-${TIMESTAMP}.xml" "$OUTPUT_DIR/sbom-latest.xml"

info "SBOM generation complete!"
info "Files created:"
ls -la "$OUTPUT_DIR"/sbom-*

echo ""
info "To view the SBOM:"
echo "  cat $OUTPUT_DIR/sbom-latest.json | python -m json.tool | head -50"
