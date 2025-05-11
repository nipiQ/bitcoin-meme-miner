import time
import logging
from utils import get_rpc_connection, process_tx

logger = logging.getLogger("mempool_scanner")
logging.basicConfig(level=logging.INFO)

rpc_connection = get_rpc_connection()

def scan_mempool(seen_txids: set) -> None:
    logger.info("[MempoolScanner] Monitoring mempool for new transactions...")
    while True:
        try:
            mempool_txids = rpc_connection.getrawmempool()
            for txid in mempool_txids:
                if txid not in seen_txids:
                    try:
                        tx = rpc_connection.getrawtransaction(txid, 2)
                        # Use the enhanced process_tx function that checks all extraction methods
                        process_tx(tx, block_height=None, is_mempool=True)
                        seen_txids.add(txid)
                    except Exception as e:
                        logger.error(f"[MempoolScanner] Error processing tx {txid}: {e}")
                        continue
            time.sleep(2)
        except Exception as e:
            logger.error(f"[MempoolScanner] Error: {e}")
            time.sleep(5)