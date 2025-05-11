#!/usr/bin/env python
"""
Look up images for a specific Bitcoin transaction ID.

Usage: python lookup_image.py <txid> [--scan]

Options:
  --scan   Force scan the transaction even if it's already indexed
"""
import sys
import os
import argparse
from monitor_images import lookup_image, process_tx
from utils import get_rpc_connection, display_image
import json
import logging

logger = logging.getLogger("lookup_image")
logging.basicConfig(level=logging.INFO)

def main() -> int:
    parser = argparse.ArgumentParser(description="Look up images in a Bitcoin transaction")
    parser.add_argument("txid", help="Transaction ID to look up")
    parser.add_argument("--scan", action="store_true", help="Force scan the transaction")
    args = parser.parse_args()
    
    txid = args.txid
    force_scan = args.scan
    
    # First, try to look up from the local index (unless force_scan is True)
    entries = None
    if not force_scan:
        logger.info(f"Looking up transaction {txid} in local index...")
        entries = lookup_image(txid)
    
    # If not found in index, try to fetch from blockchain and process
    if not entries:
        logger.info(f"Transaction {txid} not found in local index. Attempting to fetch from blockchain...")
        try:
            rpc_connection = get_rpc_connection()
            tx = rpc_connection.getrawtransaction(txid, 2)
            from monitor_images import process_tx
            
            logger.info(f"Processing transaction {txid}...")
            process_tx(tx)
            
            # Look up again to see if we found anything
            entries = lookup_image(txid)
            if not entries:
                logger.info(f"No images found in transaction {txid}.")
            
        except Exception as e:
            logger.error(f"Error fetching transaction {txid}: {e}")
            return 1
    
    # If we found images, display them again
    if entries:
        for entry in entries:
            filename = entry.get('filename')
            if filename and os.path.exists(filename):
                img_type = entry.get('image_type', 'png')
                with open(filename, 'rb') as f:
                    img_data = f.read()
                
                print(f"\nDisplaying image: {filename}")
                print("Image metadata:")
                print(json.dumps(entry, indent=2))
                
                # Use the display function to show the image in terminal
                display_image(img_data, img_type, txid)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
