#!/usr/bin/env python
"""
Search the image index for images matching specific criteria.

Usage: python search_images.py [--type=FORMAT] [--method=METHOD] [--block-range=MIN-MAX] [--extract-method=METHOD]

Options:
  --type=FORMAT        Filter by image format (png, jpeg, gif, bmp)
  --method=METHOD      Filter by extraction method (ordinal, taproot_annex, op_return, etc.)
  --block-range=MIN-MAX  Filter by block height range (e.g., 800000-810000)
  --extract-method=METHOD Alias for --method
  --limit=N            Limit results to N entries (default: 10)
"""
import os
import json
import sys
import argparse
import logging
from utils import display_image

logger = logging.getLogger("search_images")
logging.basicConfig(level=logging.INFO)

def load_index() -> dict | None:
    """Load the image index file"""
    index_file = "images/index.json"
    if not os.path.isfile(index_file):
        logger.error("No index file found.")
        return None
    
    try:
        with open(index_file, "r") as jf:
            return json.load(jf)
    except Exception as e:
        logger.error(f"Error loading index: {e}")
        return None

def search_images(index: dict, criteria: dict) -> list:
    """Search for images matching the given criteria"""
    if not index:
        return []
    
    results = []
    
    # Extract search criteria
    img_type = criteria.get("type")
    method = criteria.get("method")
    block_min = criteria.get("block_min")
    block_max = criteria.get("block_max")
    limit = criteria.get("limit", 10)
    
    for txid, entries in index.items():
        for entry in entries:
            # Check if entry matches all criteria
            match = True
            
            # Image type filter
            if img_type and entry.get("image_type") != img_type:
                match = False
            
            # Method filter
            if method:
                entry_method = entry.get("extraction_method", entry.get("inscription_type", "unknown"))
                if entry_method != method:
                    match = False
            
            # Block range filter
            if block_min is not None or block_max is not None:
                block_height = entry.get("block_height")
                if block_height is None:
                    match = False
                else:
                    if block_min is not None and block_height < block_min:
                        match = False
                    if block_max is not None and block_height > block_max:
                        match = False
            
            # If all criteria match, add to results
            if match:
                # Add txid to the entry for reference
                result = entry.copy()
                result["txid"] = txid
                results.append(result)
                
                # Check if we've reached the limit
                if len(results) >= limit:
                    break
    
    return results

def main():
    parser = argparse.ArgumentParser(description="Search for images in the Bitcoin blockchain")
    parser.add_argument("--type", choices=["png", "jpeg", "gif", "bmp"], 
                       help="Filter by image format")
    parser.add_argument("--method", help="Filter by extraction method")
    parser.add_argument("--extract-method", dest="method", 
                       help="Alias for --method")
    parser.add_argument("--block-range", help="Filter by block height range (e.g., 800000-810000)")
    parser.add_argument("--limit", type=int, default=10, 
                       help="Limit results (default: 10)")
    parser.add_argument("--display", action="store_true", 
                       help="Display images in terminal")
    
    args = parser.parse_args()
    
    # Process block range if provided
    block_min = None
    block_max = None
    if args.block_range:
        try:
            parts = args.block_range.split("-")
            if len(parts) == 2:
                block_min = int(parts[0])
                block_max = int(parts[1])
            elif len(parts) == 1:
                block_min = int(parts[0])
                block_max = block_min
        except ValueError:
            logger.error("Invalid block range format. Use: MIN-MAX")
            return 1
    
    # Build search criteria
    criteria = {
        "type": args.type,
        "method": args.method,
        "block_min": block_min,
        "block_max": block_max,
        "limit": args.limit
    }
    
    # Load index and search
    index = load_index()
    if not index:
        logger.error("No image data available for searching.")
        return 1
    
    results = search_images(index, criteria)
    
    # Display results
    if results:
        logger.info(f"Found {len(results)} matching images:")
        for i, entry in enumerate(results):
            txid = entry["txid"]
            filename = entry.get("filename", "unknown")
            img_type = entry.get("image_type", "unknown")
            extraction = entry.get("extraction_method", entry.get("inscription_type", "unknown"))
            block = entry.get("block_height", "mempool")
            
            logger.info(f"\n{i+1}. Image in tx {txid}")
            logger.info(f"   Type: {img_type}")
            logger.info(f"   Extraction: {extraction}")
            logger.info(f"   Block: {block}")
            logger.info(f"   File: {filename}")
            
            # Display image if requested and file exists
            if args.display and os.path.exists(filename):
                try:
                    with open(filename, "rb") as f:
                        img_data = f.read()
                    display_image(img_data, img_type, txid)
                except Exception as e:
                    logger.error(f"   Error displaying image: {e}")
    else:
        logger.info("No images found matching the search criteria.")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
