import os
import time
import csv
import json
from datetime import datetime
from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException
from dotenv import load_dotenv
import base64
import tempfile
import subprocess
import threading
from mempool_scanner import scan_mempool
from block_scanner import scan_blocks
from utils import (
    extract_images_from_witness, 
    extract_images_from_op_return,
    extract_images_from_corrupted_outputs, 
    extract_ipfs_references,
    display_image,
    process_tx
)
import logging

# Load environment variables from .env
load_dotenv()

# RPC connection details from .env
rpc_user = os.getenv("BITCOIN_RPC_USER")
rpc_password = os.getenv("BITCOIN_RPC_PASSWORD")
rpc_host = os.getenv("BITCOIN_RPC_HOST")
rpc_port = os.getenv("BITCOIN_RPC_PORT")
rpc_connection = AuthServiceProxy(f"http://{rpc_user}:{rpc_password}@{rpc_host}:{rpc_port}")

logger = logging.getLogger("monitor_images")
logging.basicConfig(level=logging.INFO)

def lookup_image(txid: str) -> list | None:
    """
    Look up images for a specific transaction ID in the local index.
    Returns the index entries if found, None otherwise.
    """
    index_file = "images/index.json"
    if not os.path.isfile(index_file):
        logger.error("No index file found.")
        return None
    
    try:
        with open(index_file, "r") as jf:
            index = json.load(jf)
            if txid in index:
                entries = index[txid]
                logger.info(f"Found {len(entries)} image(s) for txid {txid}:")
                for i, entry in enumerate(entries):
                    logger.info(f"\nImage {i+1}/{len(entries)}:")
                    
                    # Display key metadata
                    logger.info(f"  Type: {entry.get('extraction_method', 'unknown')}")
                    logger.info(f"  Format: {entry.get('image_type', 'unknown')}")
                    
                    # Display file information if available
                    if "filename" in entry:
                        filename = entry["filename"]
                        logger.info(f"  Filename: {filename}")
                        
                        # Check if the file exists
                        if os.path.exists(filename):
                            file_size = os.path.getsize(filename)
                            logger.info(f"  File size: {file_size} bytes")
                            
                            # If requested, display the image
                            should_display = input("Display this image? [y/N]: ").lower() == 'y'
                            if should_display:
                                subprocess.run(["viu", filename])
                        else:
                            logger.warning(f"  [WARNING] File doesn't exist: {filename}")
                return entries
        
        logger.info("No images found for txid:", txid)
    except Exception as e:
        logger.error(f"Error reading index: {e}")
    
    return None

if __name__ == "__main__":
    seen_txids = set()
    
    # If we pass None to scan_blocks:
    # 1. It will first try to use the last processed block from state.json
    # 2. If no state file or empty state, it will use block 896070 as default starting point
    # You can override by specifying a block height here
    start_height = None
    
    t1 = threading.Thread(target=scan_mempool, args=(seen_txids,), daemon=True)
    t2 = threading.Thread(target=scan_blocks, args=(seen_txids, start_height), daemon=True)
    t1.start()
    t2.start()
    logger.info("[Main] Real-time blockchain image monitor started. Press Ctrl+C to exit.")
    try:
        while True:
            t1.join(1)
            t2.join(1)
    except KeyboardInterrupt:
        logger.info("[Main] Exiting monitor.")