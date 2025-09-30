#!/bin/bash
# UR10 WebSocket Jog Control Interface Uninstall Script
# Author: jsecco ®

set -e

echo "=========================================="
echo "UR10 WebSocket Jog Control Interface"
echo "Uninstall Script v1.0.0"
echo "Author: jsecco ®"
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_DIR="$SCRIPT_DIR"

log_info "Uninstalling UR10 WebSocket Jog Control Interface..."
log_info "Project directory: $PROJECT_DIR"

# Ask for confirmation
echo ""
log_warning "⚠️  This will remove:"
echo "  • Python virtual environment ($PROJECT_DIR/venv)"
echo "  • Desktop launcher"
echo "  • Systemd service file"
echo "  • Run script"
echo ""
log_info "The following will be PRESERVED:"
echo "  • Configuration files (config/)"
echo "  • Log files (logs/)"
echo "  • Source code (src/)"
echo ""
read -p "Are you sure you want to continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_info "Uninstallation cancelled."
    exit 0
fi

# Stop and remove systemd service if it exists
if systemctl --user is-enabled ur10-jog-control.service &> /dev/null; then
    log_info "Stopping and disabling systemd service..."
    systemctl --user stop ur10-jog-control.service || true
    systemctl --user disable ur10-jog-control.service || true
    log_success "Systemd service stopped and disabled"
fi

# Remove virtual environment
if [ -d "$PROJECT_DIR/venv" ]; then
    log_info "Removing Python virtual environment..."
    rm -rf "$PROJECT_DIR/venv"
    log_success "Virtual environment removed"
fi

# Remove desktop launcher
if [ -f "$PROJECT_DIR/ur10-jog-control.desktop" ]; then
    log_info "Removing desktop launcher..."
    rm -f "$PROJECT_DIR/ur10-jog-control.desktop"
    log_success "Desktop launcher removed"
fi

# Remove run script
if [ -f "$PROJECT_DIR/run.sh" ]; then
    log_info "Removing run script..."
    rm -f "$PROJECT_DIR/run.sh"
    log_success "Run script removed"
fi

# Remove systemd service file
if [ -f "$PROJECT_DIR/ur10-jog-control.service" ]; then
    log_info "Removing systemd service file..."
    rm -f "$PROJECT_DIR/ur10-jog-control.service"
    log_success "Systemd service file removed"
fi

# Remove __pycache__ directories
log_info "Cleaning up Python cache files..."
find "$PROJECT_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$PROJECT_DIR" -name "*.pyc" -delete 2>/dev/null || true
log_success "Python cache files cleaned"

# Display summary
echo ""
log_success "Uninstallation completed!"
echo ""
echo "=========================================="
echo "UNINSTALLATION SUMMARY"
echo "=========================================="
echo ""
log_info "✅ Removed:"
echo "  • Python virtual environment"
echo "  • Desktop launcher"
echo "  • Run script"
echo "  • Systemd service file"
echo "  • Python cache files"
echo ""
log_info "📁 Preserved:"
echo "  • Source code: $PROJECT_DIR/src/"
echo "  • Configuration: $PROJECT_DIR/config/"
echo "  • Logs: $PROJECT_DIR/logs/"
echo "  • Documentation: $PROJECT_DIR/docs/"
echo "  • Installation script: $PROJECT_DIR/install.sh"
echo ""
log_info "💡 To completely remove everything:"
echo "  rm -rf $PROJECT_DIR"
echo ""
log_info "💡 To reinstall:"
echo "  cd $PROJECT_DIR && ./install.sh"
echo ""
echo "=========================================="
log_success "UR10 Jog Control Interface uninstalled!"
echo "=========================================="
