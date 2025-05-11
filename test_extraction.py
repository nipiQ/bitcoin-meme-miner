#!/usr/bin/env python
"""
Test script to verify all image extraction methods using known examples.

This script helps validate that the extraction methods are working correctly
by testing against known transactions with embedded images.
"""
import sys
import logging
from utils import (
    get_rpc_connection,
    extract_images_from_witness,
    extract_images_from_op_return,
    extract_images_from_corrupted_outputs,
    extract_ipfs_references,
    display_image
)

logger = logging.getLogger("test_extraction")
logging.basicConfig(level=logging.INFO)

# Known test cases for each extraction method
TEST_TXIDS = {
    "ordinal": [
        # Known ordinal inscription transactions
        "b78748f2ee3222d9bf4b23ab917136c745531ccc5ef8097235d11e16483e466f",  # PNG example
        "8bae12b5f4c7d8de201d503fdcf749945d1c6b1830955f1cb3f3b8cacf0f25fd"   # GIF example
    ],
    "op_return": [
        # Transactions with images in OP_RETURN outputs
        "78f0e6de0ce007f4dd4a09085e649d7e354f70bc7da06d697b167f353f115b8e"  # From bitfossil.com
    ],
    "taproot_annex": [
        # Taproot annex with image data
        "b1fcf5484c8df2ceec6c355fcca0044b013e5b0424e3086b9bc369f4a6405ff4"  # Example from Twitter/X
    ],
    "corrupted_output": [
        # Transactions with non-standard outputs containing image data
        "5c5e196e7b5a6e8e5752ab9f0bb4d98c6998d11bf3cbcd85e4902e79c45b6781"
    ],
    "ipfs": [
        # Transactions with IPFS CIDs
        "35105ff989acdf8eab2205dbe5dc84e0c1451c953da2ba10a8cbc4eeafddf269"  # Contains IPFS reference
    ]
}

def test_extraction_method(extraction_type: str, txid: str) -> bool:
    """Test a specific extraction method with a known transaction"""
    logger.info(f"Testing {extraction_type} extraction with tx {txid}")
    
    try:
        rpc = get_rpc_connection()
        tx = rpc.getrawtransaction(txid, 2)
        
        images = []
        
        if extraction_type == "ordinal":
            for vin_idx, vin in enumerate(tx.get('vin', [])):
                witness = vin.get('txinwitness', [])
                if witness:
                    witness_images = extract_images_from_witness(witness)
                    for wit_idx, img_data, img_type in witness_images:
                        logger.info(f"  Found {img_type} image in witness {wit_idx}")
                        display_image(img_data, img_type, txid, vin_idx, wit_idx, None, tx)
                        images.append((img_data, img_type))
                    
        elif extraction_type == "op_return":
            op_return_images = extract_images_from_op_return(tx)
            for img_data, img_type in op_return_images:
                logger.info(f"  Found {img_type} image in OP_RETURN")
                display_image(img_data, img_type, txid, None, None, None, tx, source_type="op_return")
                images.append((img_data, img_type))
                
        elif extraction_type == "corrupted_output":
            corrupted_images = extract_images_from_corrupted_outputs(tx)
            for img_data, img_type in corrupted_images:
                logger.info(f"  Found {img_type} image in corrupted output")
                display_image(img_data, img_type, txid, None, None, None, tx, source_type="corrupted_output")
                images.append((img_data, img_type))
                
        elif extraction_type == "ipfs":
            ipfs_images = extract_ipfs_references(tx)
            for img_data, img_type in ipfs_images:
                logger.info(f"  Found {img_type} image from IPFS reference")
                display_image(img_data, img_type, txid, None, None, None, tx, source_type="ipfs")
                images.append((img_data, img_type))
                
        elif extraction_type == "taproot_annex":
            for vin_idx, vin in enumerate(tx.get('vin', [])):
                witness = vin.get('txinwitness', [])
                if witness:
                    # Filter for only items starting with '50' (annex)
                    annex_items = [w for w in witness if w.startswith('50')]
                    if annex_items:
                        witness_images = extract_images_from_witness(annex_items)
                        for wit_idx, img_data, img_type in witness_images:
                            logger.info(f"  Found {img_type} image in Taproot annex")
                            display_image(img_data, img_type, txid, vin_idx, None, None, tx, source_type="taproot_annex")
                            images.append((img_data, img_type))
        
        logger.info(f"  {extraction_type} extraction result: {len(images)} images found")
        return len(images) > 0
        
    except Exception as e:
        logger.error(f"  Error testing {extraction_type} extraction: {e}")
        return False

def main() -> int:
    results = {method: 0 for method in TEST_TXIDS.keys()}
    
    for method, txids in TEST_TXIDS.items():
        logger.info(f"\nTesting {method.upper()} extraction method")
        logger.info("-" * 40)
        
        for txid in txids:
            success = test_extraction_method(method, txid)
            if success:
                results[method] += 1
    
    # Print summary
    logger.info("\nTEST RESULTS SUMMARY")
    logger.info("=" * 40)
    all_passed = True
    for method, success_count in results.items():
        total = len(TEST_TXIDS[method])
        if success_count == total:
            status = "PASS"
        else:
            status = f"FAIL ({success_count}/{total})"
            all_passed = False
        logger.info(f"{method.ljust(20)} : {status}")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
