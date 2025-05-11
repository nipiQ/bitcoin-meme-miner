#!/usr/bin/env python
"""
Batch scan a range of blocks to find embedded images.
This is useful for scanning historical blocks or testing extraction methods.

Usage: 
  python batch_scan.py <start_block> <end_block> [--skip-blocks=N]

Example:
  python batch_scan.py 890000 890100 --skip-blocks=10
"""
import sys
import argparse
import logging
from utils import get_rpc_connection, save_last_processed_block
from monitor_images import process_tx

logger = logging.getLogger("batch_scan")
logging.basicConfig(level=logging.INFO)

def batch_scan(start_block: int, end_block: int, skip_blocks: int = 1, seen_txids: set = None) -> bool:
    """
    Scan a range of blocks for images.
    
    Args:
        start_block: Starting block height
        end_block: Ending block height (inclusive)
        skip_blocks: Number of blocks to skip between each scan (default: 1)
        seen_txids: Set of already seen transaction IDs
    """
    if seen_txids is None:
        seen_txids = set()
        
    rpc_connection = get_rpc_connection()
    
    # Validate block range
    chain_info = rpc_connection.getblockchaininfo()
    current_height = chain_info['blocks']
    
    if end_block > current_height:
        logger.error(f"End block {end_block} is beyond current chain height {current_height}")
        end_block = current_height
    
    if start_block < 0 or start_block > end_block:
        logger.error(f"Invalid block range: {start_block}-{end_block}")
        return False
    
    pruned_height = chain_info.get('pruneheight', 0)
    if start_block < pruned_height:
        logger.error(f"Start block {start_block} is below pruned height {pruned_height}")
        start_block = pruned_height + 1
    
    # Calculate total blocks to scan
    blocks_to_scan = len(range(start_block, end_block + 1, skip_blocks))
    logger.info(f"Scanning {blocks_to_scan} blocks from {start_block} to {end_block}")
    
    # Track progress and stats
    processed_blocks = 0
    processed_txs = 0
    found_images = 0  # Track images found
    
    try:
        # Process blocks in the range
        for height in range(start_block, end_block + 1, skip_blocks):
            try:
                block_hash = rpc_connection.getblockhash(height)
                block = rpc_connection.getblock(block_hash)
                block_txs = len(block['tx'])
                
                # Update progress
                processed_blocks += 1
                progress = (processed_blocks / blocks_to_scan) * 100
                logger.info(f"Block {height} ({progress:.1f}%) - Processing {block_txs} transactions")
                
                # Process each transaction
                block_images = 0
                for txid in block['tx']:
                    if txid not in seen_txids:
                        try:
                            tx = rpc_connection.getrawtransaction(txid, 2, block_hash)
                            
                            # Track images before processing
                            image_count_before = count_images_in_index(txid)
                            
                            # Process the transaction
                            process_tx(tx, block_height=height, is_mempool=False)
                            
                            # Check if images were found
                            image_count_after = count_images_in_index(txid)
                            new_images = image_count_after - image_count_before
                            if new_images > 0:
                                block_images += new_images
                                found_images += new_images
                                logger.info(f"  Found {new_images} image(s) in tx {txid}")
                            
                            seen_txids.add(txid)
                            processed_txs += 1
                            
                        except Exception as e:
                            logger.error(f"  Error processing tx {txid}: {e}")
                
                if block_images > 0:
                    logger.info(f"  Block {height} total: {block_images} images")
                
                # Update checkpoint every 10 blocks
                if processed_blocks % 10 == 0:
                    save_last_processed_block(height)
                
            except Exception as e:
                logger.error(f"Error processing block {height}: {e}")
        
        # Final stats
        logger.info("\nBatch scan complete!")
        logger.info(f"Processed {processed_blocks} blocks with {processed_txs} transactions")
        logger.info(f"Found {found_images} images\n")
        
        return True
        
    except KeyboardInterrupt:
        logger.info("\nBatch scan interrupted by user")
        logger.info(f"Progress: {processed_blocks}/{blocks_to_scan} blocks scanned")
        logger.info(f"Found {found_images} images so far\n")
        return False

def count_images_in_index(txid):
    """Count how many images are in the index for a given transaction"""
    import json
    import os
    
    index_file = "images/index.json"
    if not os.path.isfile(index_file):
        return 0
        
    try:
        with open(index_file, "r") as jf:
            index = json.load(jf)
        if txid in index:
            return len(index[txid])
    except:
        pass
        
    return 0

def main():
    parser = argparse.ArgumentParser(
        description='Batch scan blocks for embedded images'
    )
    parser.add_argument('start_block', type=int, help='Starting block height')
    parser.add_argument('end_block', type=int, help='Ending block height (inclusive)')
    parser.add_argument('--skip-blocks', type=int, default=1, 
                        help='Number of blocks to skip between scans (default: 1)')
    
    args = parser.parse_args()
    
    return 0 if batch_scan(args.start_block, args.end_block, args.skip_blocks) else 1

if __name__ == "__main__":
    sys.exit(main())
