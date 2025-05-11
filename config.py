#!/usr/bin/env python3
"""
Configuration utility for the Bitcoin Meme Miner

This script allows you to set configuration parameters for the meme miner,
including filtering options and validation strictness.
"""

import os
import argparse
import json
from dotenv import load_dotenv, set_key

# Default configuration file
CONFIG_FILE = ".env"

def parse_args():
    parser = argparse.ArgumentParser(description="Configure Bitcoin Meme Miner settings")
    
    # Image filtering options
    parser.add_argument("--min-size", type=int, default=None, 
                        help="Minimum image size in bytes (default: 100)")
    parser.add_argument("--strict-validation", action="store_true",
                        help="Enable strict image validation (rejects corrupted images)")
    parser.add_argument("--skip-display", action="store_true",
                        help="Skip displaying images in terminal")
    parser.add_argument("--formats", type=str, default=None,
                        help="Comma-separated list of allowed image formats (default: png,jpeg,gif,bmp)")
    
    # Output options
    parser.add_argument("--show", action="store_true",
                        help="Show current configuration")
    parser.add_argument("--reset", action="store_true",
                        help="Reset to default configuration")
    
    return parser.parse_args()

def load_config():
    """Load the current configuration from .env file"""
    load_dotenv(CONFIG_FILE)
    
    config = {
        "MIN_IMAGE_SIZE": os.getenv("MIN_IMAGE_SIZE", "100"),
        "STRICT_VALIDATION": os.getenv("STRICT_VALIDATION", "0"),
        "SKIP_DISPLAY": os.getenv("SKIP_DISPLAY", "0"),
        "ALLOWED_FORMATS": os.getenv("ALLOWED_FORMATS", "png,jpeg,gif,bmp")
    }
    
    return config

def save_config(config):
    """Save configuration to .env file"""
    for key, value in config.items():
        set_key(CONFIG_FILE, key, str(value))

def show_config(config):
    """Display the current configuration in a readable format"""
    print("\n=== Bitcoin Meme Miner Configuration ===")
    print(f"Minimum image size: {config['MIN_IMAGE_SIZE']} bytes")
    print(f"Strict validation: {'Enabled' if config['STRICT_VALIDATION'] == '1' else 'Disabled'}")
    print(f"Display images: {'Disabled' if config['SKIP_DISPLAY'] == '1' else 'Enabled'}")
    print(f"Allowed formats: {config['ALLOWED_FORMATS']}")
    print("===================================\n")

def main():
    args = parse_args()
    
    # Create config file if it doesn't exist
    if not os.path.exists(CONFIG_FILE):
        open(CONFIG_FILE, 'a').close()
    
    # Load existing config
    config = load_config()
    
    # Handle reset
    if args.reset:
        config = {
            "MIN_IMAGE_SIZE": "100", 
            "STRICT_VALIDATION": "0",
            "SKIP_DISPLAY": "0",
            "ALLOWED_FORMATS": "png,jpeg,gif,bmp"
        }
        save_config(config)
        print("Configuration reset to defaults.")
    
    # Update config with new values
    if args.min_size is not None:
        config["MIN_IMAGE_SIZE"] = str(args.min_size)
    
    if args.strict_validation:
        config["STRICT_VALIDATION"] = "1"
        
    if args.skip_display:
        config["SKIP_DISPLAY"] = "1"
        
    if args.formats is not None:
        config["ALLOWED_FORMATS"] = args.formats
    
    # Save the updated configuration
    save_config(config)
    
    # Show current config if requested or if changes were made
    if args.show or any([args.min_size is not None, args.strict_validation, 
                      args.skip_display, args.formats is not None]):
        show_config(config)

if __name__ == "__main__":
    main()
