import time
import logging
from utils import (
    get_rpc_connection, get_last_processed_block, save_last_processed_block,
    process_tx
)

logger = logging.getLogger("block_scanner")
logging.basicConfig(level=logging.INFO)

rpc_connection = get_rpc_connection()

def scan_blocks(seen_txids: set, start_height: int = None) -> None:
    logger.info("[BlockScanner] Monitoring new blocks for transactions...")
    last_block_hash = None
    current_height = None
    DEFAULT_START_BLOCK = 896070  # Set default starting block
    
    # Try to load last processed block height from state file
    if start_height is None:
        start_height = get_last_processed_block()
        if start_height is not None:
            logger.info(f"[BlockScanner] Resuming from last processed block: {start_height}")
        else:
            # If no state, use the default starting block
            start_height = DEFAULT_START_BLOCK
            logger.info(f"[BlockScanner] No state found, starting from default block: {start_height}")
    
    if start_height is not None:
        try:
            # Check if the start_height is valid (within range)
            chain_info = rpc_connection.getblockchaininfo()
            current_chain_height = chain_info['blocks']
            
            # If the stored height is higher than what's available, use current tip - 1
            if start_height > current_chain_height:
                logger.info(f"[BlockScanner] Stored height {start_height} is higher than chain tip {current_chain_height}, adjusting...")
                start_height = max(current_chain_height - 1, 0)
                
            # If the stored height is too old (pruned), use the earliest available
            if start_height < chain_info.get('pruneheight', 0):
                logger.info(f"[BlockScanner] Stored height {start_height} is lower than pruned height {chain_info.get('pruneheight', 0)}, adjusting...")
                start_height = chain_info.get('pruneheight', 0) + 1
                
            block_hash = rpc_connection.getblockhash(start_height)
            last_block_hash = None  # So we process the start block
            current_height = start_height
            logger.info(f"[BlockScanner] Starting scan at block height: {start_height}")
        except Exception as e:
            logger.error(f"[BlockScanner] Invalid start_height {start_height}: {e}")
            current_height = None
            
    while True:
        try:
            # Handle fixed height scanning vs tip scanning
            if current_height is not None:
                try:
                    block_hash = rpc_connection.getblockhash(current_height)
                except Exception as e:
                    # If we hit an error (like block height out of range),
                    # revert to scanning from the tip
                    logger.error(f"[BlockScanner] Error getting block at height {current_height}: {e}")
                    logger.info("[BlockScanner] Switching to tip-based scanning")
                    current_height = None
                    continue
            else:
                block_hash = rpc_connection.getbestblockhash()
            
            if block_hash != last_block_hash:
                block = rpc_connection.getblock(block_hash)
                logger.info(f"[BlockScanner] New block: {block['height']} ({block_hash}) with {len(block['tx'])} txs")
                
                for txid in block['tx']:
                    if txid not in seen_txids:
                        try:
                            # Get full transaction details
                            tx = rpc_connection.getrawtransaction(txid, 2, block_hash)
                            
                            # Use the enhanced process_tx function that checks all extraction methods
                            process_tx(tx, block_height=block['height'], is_mempool=False)
                            
                            # Mark as seen
                            seen_txids.add(txid)
                        except Exception as e:
                            logger.error(f"[BlockScanner] Error processing tx {txid}: {e}")
                            continue
                
                # Save the current block height to state file
                save_last_processed_block(block['height'])
                last_block_hash = block_hash
                
                if current_height is not None:
                    current_height += 1
                else:
                    # When scanning at tip, store the current tip height
                    # so we resume from the next block on restart
                    current_height = block['height'] + 1
                    
            time.sleep(2)
        except Exception as e:
            logger.error(f"[BlockScanner] Error: {e}")
            time.sleep(5)