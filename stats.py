#!/usr/bin/env python
"""
Generate statistics about the images found in the Bitcoin blockchain.

Usage: python stats.py [--output=FORMAT]

Options:
  --output=FORMAT   Output format (text, json, csv) - defaults to text
"""
import os
import sys
import json
import argparse
import logging
from datetime import datetime
from collections import Counter, defaultdict

logger = logging.getLogger("stats")
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

def generate_statistics(index: dict) -> dict | None:
    """Generate statistics from the image index"""
    if not index:
        return None
    
    stats = {
        "total_images": 0,
        "total_txs": len(index),
        "by_source": Counter(),
        "by_type": Counter(),
        "by_extraction_method": Counter(),
        "by_image_type": Counter(),
        "blocks": set(),
        "first_image": None,
        "last_image": None,
        "by_month": defaultdict(int),
        "image_sizes": {
            "min": float('inf'),
            "max": 0,
            "avg": 0,
            "total": 0
        }
    }
    
    # Process all entries
    image_count = 0
    total_size = 0
    min_size = float('inf')
    max_size = 0
    
    earliest_timestamp = None
    latest_timestamp = None
    
    for txid, entries in index.items():
        for entry in entries:
            image_count += 1
            
            # Source (mempool or block)
            source = entry.get("source", "unknown")
            stats["by_source"][source] += 1
            
            # Extraction method
            method = entry.get("extraction_method", entry.get("inscription_type", "unknown"))
            stats["by_extraction_method"][method] += 1
            
            # Image type
            img_type = entry.get("image_type", "unknown")
            stats["by_image_type"][img_type] += 1
            
            # Block height (if available)
            if "block_height" in entry:
                stats["blocks"].add(entry["block_height"])
            
            # Timestamp
            if "timestamp" in entry:
                try:
                    ts = datetime.fromisoformat(entry["timestamp"])
                    month_key = ts.strftime("%Y-%m")
                    stats["by_month"][month_key] += 1
                    
                    # Track earliest and latest
                    if earliest_timestamp is None or ts < earliest_timestamp:
                        earliest_timestamp = ts
                    if latest_timestamp is None or ts > latest_timestamp:
                        latest_timestamp = ts
                except:
                    pass
            
            # File size
            if "filename" in entry and os.path.exists(entry["filename"]):
                file_size = os.path.getsize(entry["filename"])
                total_size += file_size
                min_size = min(min_size, file_size)
                max_size = max(max_size, file_size)
    
    # Update statistics
    stats["total_images"] = image_count
    
    if image_count > 0:
        stats["image_sizes"]["min"] = min_size if min_size != float('inf') else 0
        stats["image_sizes"]["max"] = max_size
        stats["image_sizes"]["avg"] = total_size / image_count
        stats["image_sizes"]["total"] = total_size
    
    if earliest_timestamp:
        stats["first_image"] = earliest_timestamp.isoformat()
    if latest_timestamp:
        stats["last_image"] = latest_timestamp.isoformat()
    
    # Sort the monthly data
    stats["by_month"] = dict(sorted(stats["by_month"].items()))
    
    return stats

def format_bytes(size: int) -> str:
    """Format bytes to human-readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0

def print_text_stats(stats: dict) -> None:
    """Print statistics in text format"""
    if not stats:
        print("No statistics available")
        return
    
    print("\n📊 BITCOIN IMAGE STATISTICS 📊")
    print("=" * 40)
    
    print(f"Total images found: {stats['total_images']}")
    print(f"Total transactions: {stats['total_txs']}")
    print(f"Blocks with images: {len(stats['blocks'])}")
    
    if stats["first_image"] and stats["last_image"]:
        print(f"Timespan: {stats['first_image']} to {stats['last_image']}")
    
    print("\nStorage:")
    print(f"  Total size: {format_bytes(stats['image_sizes']['total'])}")
    print(f"  Average size: {format_bytes(stats['image_sizes']['avg'])}")
    print(f"  Min size: {format_bytes(stats['image_sizes']['min'])}")
    print(f"  Max size: {format_bytes(stats['image_sizes']['max'])}")
    
    print("\nBy source:")
    for source, count in sorted(stats["by_source"].items(), key=lambda x: x[1], reverse=True):
        print(f"  {source}: {count}")
    
    print("\nBy extraction method:")
    for method, count in sorted(stats["by_extraction_method"].items(), key=lambda x: x[1], reverse=True):
        print(f"  {method}: {count}")
    
    print("\nBy image format:")
    for img_type, count in sorted(stats["by_image_type"].items(), key=lambda x: x[1], reverse=True):
        print(f"  {img_type}: {count}")
    
    print("\nImages by month:")
    for month, count in stats["by_month"].items():
        print(f"  {month}: {count}")

def export_json_stats(stats: dict, filename: str = "image_stats.json") -> None:
    """Export statistics as JSON"""
    with open(filename, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"Statistics exported to {filename}")

def export_csv_stats(stats: dict, filename: str = "image_stats.csv") -> None:
    """Export key statistics as CSV"""
    import csv
    
    # Prepare data for CSV export
    flat_data = []
    
    # Add monthly data
    for month, count in stats["by_month"].items():
        flat_data.append({
            "category": "month",
            "key": month,
            "value": count
        })
    
    # Add image types
    for img_type, count in stats["by_image_type"].items():
        flat_data.append({
            "category": "image_type",
            "key": img_type, 
            "value": count
        })
    
    # Add extraction methods
    for method, count in stats["by_extraction_method"].items():
        flat_data.append({
            "category": "extraction_method",
            "key": method,
            "value": count
        })
    
    # Write CSV file
    with open(filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["category", "key", "value"])
        writer.writeheader()
        writer.writerows(flat_data)
    
    print(f"Statistics exported to {filename}")

def main() -> int:
    parser = argparse.ArgumentParser(description="Generate statistics about Bitcoin blockchain images")
    parser.add_argument("--output", choices=["text", "json", "csv"], default="text",
                       help="Output format (text, json, or csv)")
    args = parser.parseArgs()
    
    # Load the index
    index = load_index()
    if not index:
        print("No image data available for analysis.")
        return 1
    
    # Generate statistics
    stats = generate_statistics(index)
    if not stats:
        print("Failed to generate statistics.")
        return 1
    
    # Output based on format
    if args.output == "text":
        print_text_stats(stats)
    elif args.output == "json":
        export_json_stats(stats)
    elif args.output == "csv":
        export_csv_stats(stats)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
