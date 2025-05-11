#!/bin/zsh
# Bitcoin Meme Miner setup and test script

# Set up directories
echo "Creating project directories..."
mkdir -p images

# Check if .env file exists, create template if not
if [ ! -f .env ]; then
    echo "Creating .env template..."
    cat > .env << EOL
# Bitcoin RPC Settings
BITCOIN_RPC_USER=yourusername
BITCOIN_RPC_PASSWORD=yourpassword
BITCOIN_RPC_HOST=127.0.0.1
BITCOIN_RPC_PORT=8332
EOL
    echo "Created .env template. Please edit with your Bitcoin node credentials."
fi

# Check if viu is installed
if ! command -v viu &> /dev/null; then
    echo "Warning: 'viu' is not installed. You need it to view images in terminal."
    echo "Install with: brew install viu (macOS) or cargo install viu (Linux/macOS with Rust)"
fi

# Check Python dependencies
echo "Checking Python dependencies..."
REQUIRED_PKGS="bitcoinrpc-auth-proxy python-dotenv python-bitcoinlib requests"

for pkg in $REQUIRED_PKGS; do
    if ! pip show $pkg &> /dev/null; then
        echo "Missing package: $pkg"
        MISSING_PKGS="$MISSING_PKGS $pkg"
    fi
done

if [ ! -z "$MISSING_PKGS" ]; then
    echo "Some required packages are missing. Install them with:"
    echo "pip install$MISSING_PKGS"
fi

# Check Bitcoin node connection
if grep -q "yourusername" .env; then
    echo "Warning: You need to edit the .env file with your Bitcoin node credentials."
else
    echo "Testing Bitcoin node connection..."
    python3 -c "from utils import get_rpc_connection; rpc = get_rpc_connection(); print(f'Connected to Bitcoin node. Chain height: {rpc.getblockcount()}')" || echo "Failed to connect to Bitcoin node. Please check your .env settings."
fi

# Show help
echo ""
echo "Bitcoin Meme Miner Setup Complete"
echo "=========================="
echo "Available commands:"
echo "  python monitor_images.py          - Start real-time monitoring"
echo "  python lookup_image.py <txid>     - Look up images in a specific transaction"
echo "  python batch_scan.py <start> <end> - Scan a range of blocks"
echo "  python stats.py                   - Generate statistics of found images"
echo "  python search_images.py           - Search for images by criteria"
echo "  python test_extraction.py         - Test extraction methods"
echo ""
echo "For more information, see the README.md file."
