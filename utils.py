import os
from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException
from dotenv import load_dotenv
import base64
import tempfile
import subprocess
import json
import re
from datetime import datetime
import binascii
from bitcoin.core.script import CScript, OP_RETURN  # For parsing scripts with python-bitcoinlib
import logging

# IPFS support explicitly disabled
IPFS_AVAILABLE = False
logger = logging.getLogger("utils")
logging.basicConfig(level=logging.INFO)
logger.info("IPFS image extraction disabled - focusing only on blockchain/mempool native images")

# Original IPFS import code (commented out):
# try:
#     # Try to import ipfshttpclient for IPFS support
#     import ipfshttpclient
#     IPFS_AVAILABLE = True
# except ImportError:
#     # We'll use requests as fallback if ipfshttpclient is not available
#     try:
#         import requests
#         # We can still use HTTP gateways even without the native client
#         logger.info("Using HTTP gateway fallback for IPFS (ipfshttpclient not installed)")
#     except ImportError:
#         logger.warning("Neither ipfshttpclient nor requests available. IPFS image retrieval will be disabled.")

# Load environment variables from .env
load_dotenv()

# RPC connection details from .env
rpc_user = os.getenv("BITCOIN_RPC_USER")
rpc_password = os.getenv("BITCOIN_RPC_PASSWORD")
rpc_host = os.getenv("BITCOIN_RPC_HOST")
rpc_port = os.getenv("BITCOIN_RPC_PORT")

def get_rpc_connection():
    return AuthServiceProxy(f"http://{rpc_user}:{rpc_password}@{rpc_host}:{rpc_port}")

def process_tx(tx: dict, block_height: int = None, is_mempool: bool = False) -> None:
    """
    Process a transaction to extract images from all supported methods:
    - Witness data (Ordinals, Taproot Annex, etc.)
    - OP_RETURN outputs
    - Corrupted/non-standard outputs
    - IPFS references
    """
    txid = tx.get('txid')
    
    # Get filter settings from environment
    min_size = int(os.environ.get("MIN_IMAGE_SIZE", 30))  # Lowered from 100 to 30
    strict_validation = os.environ.get("STRICT_VALIDATION", "0") == "1"  # Default to less strict
    skip_display = os.environ.get("SKIP_DISPLAY", "0") == "1"
    allowed_formats = os.environ.get("ALLOWED_FORMATS", "png,jpeg,gif,bmp,webp").lower().split(",")  # Added webp
    force_save_invalid = os.environ.get("FORCE_SAVE_INVALID", "1") == "1"  # Save invalid images for research
    
    def should_process_image(img_data: bytes, img_type: str) -> bool:
        """Helper to check if image meets our filter criteria"""
        if len(img_data) < min_size:
            logger.info(f"[FILTER] Skipping image: too small ({len(img_data)} bytes < {min_size} bytes)")
            return False
            
        if img_type not in allowed_formats:
            logger.info(f"[FILTER] Skipping image: format not allowed ({img_type} not in {allowed_formats})")
            return False
            
        # Always perform basic validation, regardless of strict_validation setting
        # to catch extremely corrupted data early
        import io
        from PIL import Image, ImageFile, UnidentifiedImageError
        
        # For JPEG/BMP/WEBP files, do special checks for common corruption patterns
        if img_type in ('jpeg', 'jpg', 'bmp', 'webp'):
            # Check for common bad JPEG patterns
            if img_type in ('jpeg', 'jpg'):
                # Look for Bad Huffman Code patterns - specific byte sequences that often cause display errors
                bad_sequences = [
                    b'\xff\x47', b'\xff\x8a', b'\xff\xf0',    # Known Bad Huffman codes
                    b'\xff\xd9\xff\xd8',                      # JPEG EOI immediately followed by SOI (corrupt)
                    b'\xff\x00\x00', b'\xff\xc0\x00'          # Other problematic sequences
                ]
                
                for seq in bad_sequences:
                    if seq in img_data:
                        logger.info(f"[FILTER] Detected likely corrupt JPEG with {seq.hex()} sequence")
                        # Don't return here - we'll still process and save as invalid for research
                        if not force_save_invalid:
                            return False
            
            # Check for truncated BMP files
            if img_type == 'bmp' and len(img_data) < 54:
                logger.info("[FILTER] BMP header too small (likely truncated)")
                if not force_save_invalid:
                    return False
            
            # For webp, skip extra corruption checks for now (Pillow will handle most)
            pass
        
        # For strict validation, try to open and process the image
        if strict_validation:
            try:
                # Use permissive mode for initial check - we'll do stricter validation later
                ImageFile.LOAD_TRUNCATED_IMAGES = True
                
                with Image.open(io.BytesIO(img_data)) as img:
                    # Try to load the image to validate it
                    try:
                        img.load()
                        # Get image dimensions to further validate
                        if img.width < 4 or img.height < 4:
                            logger.info(f"[FILTER] Image dimensions too small ({img.width}x{img.height})")
                            if not force_save_invalid:
                                return False
                            
                        # Additional check for JPEGs - try to transcode
                        if img_type in ('jpeg', 'jpg'):
                            # Try a basic conversion as additional validation
                            test_out = io.BytesIO()
                            try:
                                img.save(test_out, format='PNG')
                            except Exception as transcode_error:
                                logger.info(f"[FILTER] Image transcode test failed: {transcode_error}")
                                # Still continue if we want to save invalid images
                                if not force_save_invalid:
                                    return False
                    except Exception as load_error:
                        logger.info(f"[FILTER] Image load failed: {load_error}")
                        # Still continue if we want to save invalid images
                        if not force_save_invalid:
                            return False
            except UnidentifiedImageError:
                logger.info("[FILTER] Image format could not be identified")
                if not force_save_invalid:
                    return False
            except Exception as e:
                logger.info(f"[FILTER] Image validation failed: {e}")
                if not force_save_invalid:
                    return False
                
        return True
    
    # 1. Check transaction inputs for witness data
    for vin_idx, vin in enumerate(tx.get('vin', [])):
        witness = vin.get('txinwitness', [])
        if witness:
            images = extract_images_from_witness(witness)
            for wit_idx, img_data, img_type in images:
                if should_process_image(img_data, img_type):
                    logger.info(f"[WITNESS] Image found in tx {txid}")
                    display_image(img_data, img_type, txid=txid, vin_idx=vin_idx, 
                                wit_idx=wit_idx, block_height=block_height, 
                                tx=tx, is_mempool=is_mempool, source_type="witness",
                                skip_display=skip_display)
    
    # 2. Check OP_RETURN outputs
    op_return_images = extract_images_from_op_return(tx)
    for img_data, img_type in op_return_images:
        if should_process_image(img_data, img_type):
            logger.info(f"[OP_RETURN] Image found in tx {txid}")
            display_image(img_data, img_type, txid=txid, block_height=block_height,
                        tx=tx, is_mempool=is_mempool, source_type="op_return",
                        skip_display=skip_display)
    
    # 3. Check for corrupted/non-standard outputs
    corrupted_images = extract_images_from_corrupted_outputs(tx)
    for img_data, img_type in corrupted_images:
        if should_process_image(img_data, img_type):
            logger.info(f"[CORRUPTED] Image found in tx {txid}")
            display_image(img_data, img_type, txid=txid, block_height=block_height,
                        tx=tx, is_mempool=is_mempool, source_type="corrupted_output",
                        skip_display=skip_display)
    
    # IPFS extraction disabled - only focusing on blockchain/mempool native images
    # 4. Check for IPFS references 
    # Commented out as we're focusing only on blockchain-native images
    # ipfs_images = extract_ipfs_references(tx)
    # for img_data, img_type in ipfs_images:
    #     logger.info(f"[IPFS] Image found in tx {txid}")
    #     display_image(img_data, img_type, txid=txid, block_height=block_height,
    #                   tx=tx, is_mempool=is_mempool, source_type="ipfs")

def get_last_processed_block() -> int | None:
    """
    Load the last processed block height from a state file
    """
    state_file = "state.json"
    if os.path.isfile(state_file):
        try:
            # Check if the file has content
            if os.path.getsize(state_file) > 0:
                with open(state_file, "r") as f:
                    state = json.load(f)
                    return state.get("last_block_height")
            else:
                logger.info("State file exists but is empty")
        except Exception as e:
            logger.error(f"Failed to load state file: {e}")
    return None

def save_last_processed_block(block_height: int) -> None:
    """
    Save the last processed block height to a state file
    """
    state_file = "state.json"
    try:
        state = {}
        if os.path.isfile(state_file):
            try:
                with open(state_file, "r") as f:
                    state = json.load(f)
            except:
                pass
        
        state["last_block_height"] = block_height
        state["last_updated"] = datetime.utcnow().isoformat()
        
        with open(state_file, "w") as f:
            json.dump(state, f, indent=2)
        logger.info(f"Saved last processed block height: {block_height}")
    except Exception as e:
        logger.error(f"Failed to save state: {e}")

def extract_images_from_witness(witness):
    """
    Scan all witness items for possible image data, using:
    - Legacy/segwit v0 (base64-encoded PNGs)
    - Taproot annex (starts with '50')
    - Ordinal inscriptions (contains 'ord' marker)
    Returns a list of (index, img_data, img_type) tuples.
    """
    images = []
    for idx, item in enumerate(witness):
        if not isinstance(item, str) or len(item) < 8:
            continue

        # Convert hex string to bytes
        try:
            # Check if string is valid hex before converting
            if not all(c in '0123456789abcdefABCDEF' for c in item):
                # Try to clean up the string - only keep hex characters
                clean_hex = ''.join(c for c in item if c in '0123456789abcdefABCDEF')
                
                # Make sure length is even (required for bytes.fromhex)
                if len(clean_hex) % 2 != 0:
                    clean_hex = clean_hex[:-1]
                
                # If too short after cleaning, skip
                if len(clean_hex) < 8:  
                    continue
                
                # Log that we had to clean the hex string
                logger.warning(f"Cleaned hex string: {len(item)} chars to {len(clean_hex)} chars")
                item = clean_hex
            
            # Add additional validation to check if it's likely a valid hex string for an image
            # We don't want to process extremely large binary data that might be something else
            if len(item) > 10000000:  # 10MB limit
                logger.info(f"[FILTER] Skipping extremely large witness data: {len(item)} chars")
                continue
                
            bin_data = bytes.fromhex(item)
            
            # Quick check for valid size - if too small, likely not an image
            if len(bin_data) < 20:  # Minimum bytes needed for image header
                continue
                
        except ValueError as e:
            logger.error(f"Failed to parse witness data: {e}, item starts with: {item[:20]}...")
            continue

        # Try Ordinal inscription detection with more robust parsing
        if b'\x00c\x03ord' in bin_data or b'ord' in bin_data:
            try:
                script = CScript(bin_data)
                # Iterate through script operations to find content type and data
                script_ops = list(script.raw_iter())
                found_ord = False
                content_type = None
                img_data = None
                content_data = None
                i = 0
                
                # First pass: look for the ord marker and metadata
                while i < len(script_ops):
                    try:
                        op, data, _ = script_ops[i]
                        
                        # Check for the ord marker pattern
                        if data == b'ord':
                            found_ord = True
                        
                        # Look for content type - follows pattern OP_FALSE OP_IF "ord" OP_1 "content-type"
                        elif found_ord and isinstance(data, bytes) and data == b'\x01':
                            # Next data should be content type
                            if i + 1 < len(script_ops):
                                _, content_type_data, _ = script_ops[i + 1]
                                if isinstance(content_type_data, bytes):
                                    try:
                                        content_type = content_type_data.decode('utf-8', errors='ignore')
                                    except:
                                        content_type = content_type_data.decode('ascii', errors='ignore')
                        
                        # Look for content data - follows content-type with OP_0
                        elif found_ord and content_type and isinstance(data, bytes) and data == b'\x00':
                            # Next data should be the content
                            if i + 1 < len(script_ops):
                                _, content_data, _ = script_ops[i + 1]
                                # We found potential content data, let's check if it's an image
                                if content_type and content_type.startswith('image/'):
                                    img_type = None
                                    # Determine image type from content type
                                    if 'png' in content_type:
                                        img_type = 'png'
                                    elif 'jpeg' in content_type or 'jpg' in content_type:
                                        img_type = 'jpeg'
                                    elif 'gif' in content_type:
                                        img_type = 'gif'
                                    elif 'bmp' in content_type:
                                        img_type = 'bmp'
                                    # Verify with magic numbers as well
                                    detected_type = identify_image_type(content_data)
                                    if detected_type:
                                        # Trust the detected type over the content-type
                                        img_type = detected_type
                                        images.append((idx, content_data, img_type))
                                        
                    except Exception as e:
                        logger.warning(f"Error parsing script operation at index {i}: {e}")
                    i += 1
                
                # If we didn't find an image via metadata, attempt direct byte search for image magic numbers
                if not content_data:
                    # Scan the whole binary data for image magic numbers
                    for img_type in ['png', 'jpeg', 'gif', 'bmp']:
                        magic_signature = None
                        if img_type == 'png':
                            magic_signature = b'\x89PNG\r\n\x1a\n'
                        elif img_type == 'jpeg':
                            magic_signature = b'\xff\xd8\xff'
                        elif img_type == 'gif':
                            # Match either gif87a or gif89a
                            magic_signature = b'GIF8' 
                        elif img_type == 'bmp':
                            magic_signature = b'BM'
                        
                        if magic_signature and magic_signature in bin_data:
                            start_idx = bin_data.index(magic_signature)
                            image_data = bin_data[start_idx:]
                            images.append((idx, image_data, img_type))
                            break
                
            except Exception as e:
                logger.error(f"Failed to parse Ordinal inscription at index {idx}: {e}")
            continue

        # Try legacy/segwit v0 (try multiple methods)
        try:
            # Method 1: Traditional base64 encoded (skip first 4 chars)
            hex_data = item[4:]
            bin_data = bytes.fromhex(hex_data)
            # Try to decode as base64
            try:
                img_data = base64.b64decode(bin_data)
                img_type = identify_image_type(img_data)
                if img_type:
                    images.append((idx, img_data, img_type))
                    continue
            except:
                pass
            
            # Method 2: Direct hex encoding (no base64)
            img_type = identify_image_type(bin_data) 
            if img_type:
                images.append((idx, bin_data, img_type))
                continue
        except Exception:
            pass

        # Try Taproot annex (starts with '50')
        if item.startswith('50'):
            try:
                annex_hex = item[2:]  # Skip the annex marker
                bin_data = bytes.fromhex(annex_hex)
                
                # Check for image magic numbers directly
                img_type = identify_image_type(bin_data)
                if img_type:
                    images.append((idx, bin_data, img_type))
                    continue
                    
                # Some annexes might have metadata prefixes, scan through the data
                for offset in range(0, min(len(bin_data), 50)):
                    slice_data = bin_data[offset:]
                    img_type = identify_image_type(slice_data)
                    if img_type:
                        images.append((idx, slice_data, img_type))
                        break
            except Exception as e:
                logger.error(f"Failed to parse Taproot annex at index {idx}: {e}")

    return images

def extract_images_from_op_return(tx):
    """
    Scan transaction outputs for OP_RETURN data that may contain images.
    
    OP_RETURN outputs are limited to 80 bytes, but images can be chunked across
    multiple transactions. This function checks for image signatures/magic numbers
    and returns any detected images.
    
    Returns a list of (img_data, img_type) tuples.
    """
    images = []
    chunks_by_prefix = {}  # For reassembling chunked images
    
    for vout in tx.get('vout', []):
        asm = vout.get('scriptPubKey', {}).get('asm', '')
        
        # Check if this is an OP_RETURN output
        if not asm.startswith('OP_RETURN'):
            continue
            
        try:
            # Extract the data after OP_RETURN
            hex_data = asm.split('OP_RETURN ')[1]
            
            # Skip data that's too short
            if len(hex_data) < 4:
                continue
            
            # Clean and validate the hex data before processing
            # Some OP_RETURN outputs might contain non-hex characters
            try:
                # Check if hex string is valid
                if not all(c in '0123456789abcdefABCDEF' for c in hex_data):
                    # Clean the string - keep only hex characters
                    clean_hex = ''.join(c for c in hex_data if c in '0123456789abcdefABCDEF')
                    
                    # Make sure length is even (required for bytes.fromhex)
                    if len(clean_hex) % 2 != 0:
                        clean_hex = clean_hex[:-1]
                    
                    # Skip if too short after cleaning
                    if len(clean_hex) < 4:
                        continue
                    
                    # Use cleaned hex data
                    hex_data = clean_hex
                    
                # Convert hex to bytes
                bin_data = bytes.fromhex(hex_data)
            except ValueError as e:
                logger.error(f"Failed to parse OP_RETURN data after cleaning: {e}, raw data: {hex_data[:20]}...")
            
            # Check if this is an image chunk with a pattern like IMG_PART_<id>_<part>_<total>
            chunk_pattern = re.search(b'IMG_PART_([0-9a-f]+)_([0-9]+)_([0-9]+)', bin_data)
            if chunk_pattern:
                img_id = chunk_pattern.group(1).decode('ascii')
                part_num = int(chunk_pattern.group(2))
                total_parts = int(chunk_pattern.group(3))
                
                # Extract the actual image data after the header
                data_start = chunk_pattern.end() + 1
                chunk_data = bin_data[data_start:]
                
                if img_id not in chunks_by_prefix:
                    chunks_by_prefix[img_id] = {'total': total_parts, 'parts': {}}
                
                chunks_by_prefix[img_id]['parts'][part_num] = chunk_data
                
                # Check if we have all parts
                if len(chunks_by_prefix[img_id]['parts']) == total_parts:
                    # Combine all parts in order
                    combined_data = b''
                    for i in range(1, total_parts + 1):
                        if i in chunks_by_prefix[img_id]['parts']:
                            combined_data += chunks_by_prefix[img_id]['parts'][i]
                    
                    # Check for image magic numbers in the combined data
                    img_type = identify_image_type(combined_data)
                    if img_type:
                        images.append((combined_data, img_type))
                
                continue
            
            # Check for direct image data (single OP_RETURN containing a small image)
            img_type = identify_image_type(bin_data)
            if img_type:
                images.append((bin_data, img_type))
                
        except Exception as e:
            logger.error(f"Failed to parse OP_RETURN data: {e}")
    
    return images

def identify_image_type(data):
    """
    Identify image type based on magic numbers/signatures.
    Returns the image type as string ('png', 'jpeg', 'gif', 'bmp', 'webp') or None if not an image.
    """
    import io
    import imghdr
    from PIL import Image, ImageFile, UnidentifiedImageError
    
    if len(data) < 8:
        return None
    
    # First check using magic numbers (faster)
    magic_type = None
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        magic_type = 'png'
    elif data.startswith(b'\xff\xd8\xff'):
        magic_type = 'jpeg'
    elif data.startswith(b'GIF89a') or data.startswith(b'GIF87a'):
        magic_type = 'gif'
    elif data.startswith(b'BM'):
        magic_type = 'bmp'
    elif data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        magic_type = 'webp'
    
    # Check for truncated or corrupted data
    data_size = len(data)
    is_truncated = False
    validation_passed = False
    
    # If we found a candidate type, do more validation
    if magic_type:
        # Basic size sanity checks by format
        if (magic_type == 'png' and data_size < 50) or \
           (magic_type == 'jpeg' and data_size < 100) or \
           (magic_type == 'gif' and data_size < 40) or \
           (magic_type == 'bmp' and data_size < 54):
            is_truncated = True
            logger.warning(f"{magic_type.upper()} data appears truncated: {data_size} bytes is too small")
        
        try:
            # Use imghdr for additional verification
            img_type_check = imghdr.what(None, data)
            
            # If imghdr returns a type and it's different, log it
            if img_type_check and img_type_check != magic_type and img_type_check != 'jpeg' and magic_type != 'jpg':
                logger.warning(f"Image type mismatch: magic={magic_type}, imghdr={img_type_check}. Using {img_type_check}.")
                magic_type = img_type_check
            
            # Check for format-specific corruption indicators
            if magic_type == 'jpeg':
                # Check for proper JPEG structure - should have SOI, APP0, DQT, SOF markers
                # But adding this creates false positives - will rely on PIL validation
                pass
                
            # Try loading with PIL as final validation (handles corrupted files better)
            try:
                img_data = io.BytesIO(data)
                p = ImageFile.Parser()
                
                # Feed the parser in chunks to better detect truncation
                chunk_size = 1024
                while True:
                    chunk = img_data.read(chunk_size)
                    if not chunk:
                        break
                    p.feed(chunk)
                
                if p.image:
                    # Additional test - verify with PIL's open
                    try:
                        with Image.open(io.BytesIO(data)) as img:
                            # Try to decode the image
                            img.load()
                            validation_passed = True
                            return magic_type
                    except Exception as e:
                        logger.warning(f"PIL image load failed: {e}")
            except Exception as e:
                # Image didn't pass PIL validation but still has correct magic bytes
                logger.warning(f"Image failed PIL validation: {e}. Still saving based on magic bytes.")
                return magic_type
        except Exception as e:
            logger.warning(f"Image validation error: {e}")
            # Fall back to magic number detection if validation fails
            return magic_type
    
    # Try imghdr for types not caught by magic numbers
    try:
        img_type = imghdr.what(None, data)
        if img_type:
            return img_type
    except:
        pass
    
    return magic_type

def display_image(img_data, img_type, txid=None, vin_idx=None, wit_idx=None, block_height=None, tx=None, is_mempool=False, source_type=None, skip_display=False):
    import json
    from datetime import datetime
    import hashlib
    import io
    from PIL import Image, UnidentifiedImageError

    # Strict validation: Only save images that can be fully loaded by Pillow
    try:
        with Image.open(io.BytesIO(img_data)) as img:
            img.load()
    except Exception as e:
        logger.info(f"[SKIP] Not a valid image: {e}")
        return

    # Passed validation, save image
    os.makedirs("images", exist_ok=True)
    if txid is not None:
        if vin_idx is not None and wit_idx is not None:
            filename = f"images/{txid}_{vin_idx}_{wit_idx}.{img_type}"
            file_id = f"{vin_idx}_{wit_idx}"
        elif vin_idx is not None:
            filename = f"images/{txid}_in{vin_idx}.{img_type}"
            file_id = f"in{vin_idx}"
        else:
            img_hash = hashlib.md5(img_data).hexdigest()[:8]
            source_prefix = source_type or "img"
            filename = f"images/{txid}_{source_prefix}_{img_hash}.{img_type}"
            file_id = f"{source_prefix}_{img_hash}"
    else:
        img_hash = hashlib.md5(img_data).hexdigest()[:16]
        filename = f"images/unknown_{img_hash}.{img_type}"
        file_id = f"unknown_{img_hash}"
        txid = f"unknown_{img_hash[:8]}"

    try:
        with open(filename, "wb") as f:
            f.write(img_data)
        logger.info(f"[VALID] Image saved to {filename}")
    except Exception as e:
        logger.error(f"Could not save image file {filename}: {e}")
        return

    # Save metadata to JSON index
    index_file = "images/index.json"
    try:
        if os.path.isfile(index_file):
            with open(index_file, "r") as jf:
                try:
                    index = json.load(jf)
                except Exception:
                    index = {}
        else:
            index = {}
        if not source_type:
            if wit_idx is not None:
                if tx:
                    source_type = identify_inscription_type(tx, wit_idx)
                else:
                    source_type = "witness"
            else:
                source_type = "unknown"
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "filename": filename,
            "image_type": img_type,
            "source": "mempool" if is_mempool else "block",
            "extraction_method": source_type,
            "size_bytes": len(img_data)
        }
        if vin_idx is not None:
            entry["vin_idx"] = vin_idx
        if wit_idx is not None:
            entry["wit_idx"] = wit_idx
        if block_height is not None:
            entry["block_height"] = block_height
        entry["image_hash"] = hashlib.sha256(img_data).hexdigest()
        if tx:
            entry["inscription_type"] = identify_inscription_type(tx, wit_idx) if wit_idx is not None else source_type
            tx_details = {
                "version": tx.get("version"),
                "locktime": tx.get("locktime"),
                "size": tx.get("size"),
                "vsize": tx.get("vsize"),
                "fee": tx.get("fee") if "fee" in tx else None,
                "confirmations": tx.get("confirmations", 0),
                "time": tx.get("time") if "time" in tx else None,
                "blocktime": tx.get("blocktime") if "blocktime" in tx else None,
                "has_witness": any(
                    "txinwitness" in vin for vin in tx.get("vin", [])
                ),
                "num_inputs": len(tx.get("vin", [])),
                "num_outputs": len(tx.get("vout", []))
            }
            entry["tx_details"] = tx_details
        should_add = True
        if txid in index:
            for existing_entry in index[txid]:
                if ((file_id and 
                     (existing_entry.get("vin_idx") == vin_idx and existing_entry.get("wit_idx") == wit_idx)) or
                    (entry.get("image_hash") and existing_entry.get("image_hash") == entry["image_hash"])):
                    if block_height and not existing_entry.get("block_height"):
                        existing_entry.update({
                            "block_height": block_height,
                            "source": "block",
                            "timestamp": entry["timestamp"]
                        })
                        logger.info(f"Updated existing entry with block information: {block_height}")
                    should_add = False
                    break
        else:
            index[txid] = []
        if should_add:
            index[txid].append(entry)
            logger.info(f"Added new entry for txid: {txid}")
        with open(index_file, "w") as jf:
            def json_serializer(obj):
                from decimal import Decimal
                if isinstance(obj, Decimal):
                    return float(obj)
                return str(obj)
            json.dump(index, jf, indent=2, default=json_serializer)
        logger.info(f"JSON index updated at {index_file}")
    except Exception as e:
        logger.error(f"Could not update {index_file}: {e}")
    if skip_display:
        logger.info("Skipping image display (disabled)")
        return
    # Display image in terminal
    with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{img_type}') as f:
        f.write(img_data)
        img_path = f.name
    display_info = f"Displaying image from txid={txid}"
    if vin_idx is not None:
        display_info += f", vin={vin_idx}"
    if wit_idx is not None:
        display_info += f", witness={wit_idx}"
    if source_type:
        display_info += f", type={source_type}"
    logger.info(display_info)
    try:
        subprocess.run(["viu", img_path], check=False)
    except Exception as e:
        logger.error(f"Failed to display image with viu: {e}")
    finally:
        os.remove(img_path)

def identify_inscription_type(tx, wit_idx):
    """
    Identify the type of inscription based on transaction details
    """
    if not tx:
        return "unknown"
    
    # Check if it's a taproot transaction
    is_taproot = False
    has_annex = False
    has_ord_marker = False
    
    try:
        # Check witness for taproot indicators
        for vin in tx.get('vin', []):
            witness = vin.get('txinwitness', [])
            if witness and len(witness) > 0:
                # Check for taproot witness (control block)
                if any(item.startswith('20') or item.startswith('21') for item in witness):
                    is_taproot = True
                # Check for annex
                if any(item.startswith('50') for item in witness):
                    has_annex = True
                # Check for ord marker
                for item in witness:
                    if isinstance(item, str) and len(item) > 12:
                        try:
                            bin_data = bytes.fromhex(item)
                            if b'\x00c\x03ord' in bin_data:
                                has_ord_marker = True
                                break
                        except:
                            pass
    except Exception as e:
        logger.error(f"Failed to identify inscription type: {e}")
    
    # Determine the type based on findings
    if has_ord_marker:
        return "ordinal"
    elif has_annex:
        return "taproot_annex"
    elif is_taproot:
        return "taproot"
    else:
        return "legacy_segwit"

def extract_images_from_corrupted_outputs(tx):
    """
    Scan transaction outputs for non-standard scriptPubKey types that may contain images.
    Some users encode images directly in outputs with corrupted/non-standard scripts.
    
    Returns a list of (img_data, img_type) tuples.
    """
    images = []
    
    for vout in tx.get('vout', []):
        script_type = vout.get('scriptPubKey', {}).get('type', '')
        
        # Skip standard script types
        if script_type in ['pubkeyhash', 'scripthash', 'witness_v0_keyhash', 
                          'witness_v0_scripthash', 'witness_v1_taproot', 'multisig', 
                          'nulldata', 'nonstandard']:
            # We still check nonstandard scripts
            if script_type != 'nonstandard':
                continue
        
        # Get the script as hex
        hex_script = vout.get('scriptPubKey', {}).get('hex', '')
        if not hex_script:
            continue
            
        try:
            # Convert hex to bytes
            bin_data = bytes.fromhex(hex_script)
            
            # Check for image signatures
            img_type = identify_image_type(bin_data)
            if img_type:
                images.append((bin_data, img_type))
                
        except Exception as e:
            logger.error(f"Failed to parse script data: {e}")
    
    return images

def extract_ipfs_references(tx):
    """
    Scan transaction data for IPFS Content Identifiers (CIDs) and retrieve images
    from IPFS if possible.
    
    IPFS CIDs typically start with 'Qm' (v0) or 'baf' (v1) and are 46+ characters.
    This function will work with either the native IPFS client or HTTP gateway fallbacks.
    
    Returns a list of (img_data, img_type) tuples.
    """
    # IPFS extraction explicitly disabled - only focusing on blockchain-native images
    return []

def retrieve_from_ipfs(cid):
    """
    Retrieve content from IPFS given a CID.
    Returns (image_data, image_type) if the content is a valid image, otherwise (None, None).
    
    This function has been disabled - only focusing on blockchain-native images.
    """
    logger.info(f"IPFS extraction disabled - not retrieving CID: {cid}")
    return None, None

def validate_image(img_data, img_type):
    """
    Perform a comprehensive validation of image data to detect corrupt images.
    Returns a tuple of (is_valid, message, image_info)
    """
    import io
    from PIL import Image, UnidentifiedImageError, ImageFile
    import imghdr

    # Early rejection for really small data
    if len(img_data) < 50:
        return False, "Image data too small", {}

    # Validate file signatures
    if img_type == 'png' and not img_data.startswith(b'\x89PNG\r\n\x1a\n'):
        return False, "Invalid PNG signature", {}
    elif img_type == 'jpeg' and not img_data.startswith(b'\xff\xd8\xff'):
        return False, "Invalid JPEG signature", {}
    elif img_type == 'gif' and not (img_data.startswith(b'GIF87a') or img_data.startswith(b'GIF89a')):
        return False, "Invalid GIF signature", {}
    elif img_type == 'bmp' and not img_data.startswith(b'BM'):
        return False, "Invalid BMP signature", {}
    elif img_type == 'webp' and not (img_data.startswith(b'RIFF') and img_data[8:12] == b'WEBP'):
        return False, "Invalid WEBP signature", {}
    
    # Double-check format with imghdr
    detected_format = imghdr.what(None, img_data)
    if detected_format and detected_format != img_type and detected_format != 'jpeg' and img_type != 'jpg':
        logger.warning(f"Format mismatch: magic says {img_type}, imghdr says {detected_format}")
    
    # Use deep validation for JPEG files to catch Huffman code errors
    if img_type in ('jpeg', 'jpg'):
        try:
            # Use pillow's parser to check for JPEG errors
            p = ImageFile.Parser()
            p.feed(img_data)
            if not p.image:
                return False, "Invalid JPEG structure (parser couldn't build image)", {}
                
            # Look for common JPEG corruption markers
            if b'xff47' in img_data.lower() or b'xfff0' in img_data.lower():
                return False, "Suspicious JPEG markers detected", {}
            
            # Additional check for corrupted JPEGs - many Bad Huffman Code errors
            # occur with specific byte patterns
            if any(pattern in img_data for pattern in [b'\xff\x00\xff', b'\xff\xc0\x00', b'\xef\xbf\xbd']):
                return False, "Corrupted JPEG data detected", {}
        except Exception as e:
            return False, f"JPEG validation error: {str(e)}", {}
    
    # Try to parse the image with PIL
    try:
        data_stream = io.BytesIO(img_data)
        with Image.open(data_stream) as img:
            # Force PIL to process the entire image
            img.load()
            
            # Get image dimensions and more info
            image_info = {
                "width": img.width,
                "height": img.height,
                "format": img.format.lower() if img.format else img_type,
                "mode": img.mode,
                "size_bytes": len(img_data)
            }
            
            # Sanity check for image dimensions - reject unreasonable sizes
            # Images can't be zero-sized
            if img.width <= 0 or img.height <= 0:
                return False, f"Invalid image dimensions: {img.width}x{img.height}", image_info
                
            # Images shouldn't be unreasonably large (over 100,000 pixels in either dimension)
            if img.width > 100000 or img.height > 100000:
                return False, f"Suspicious image dimensions: {img.width}x{img.height}", image_info
                
            # Validate size in bytes vs dimensions (very rough check)
            # For PNG/JPEG, we expect compression, but there should be some minimal size
            expected_min_bytes = (img.width * img.height) / 100  # Very rough estimate
            if len(img_data) < expected_min_bytes and len(img_data) < 10:
                return False, f"Image data too small for dimensions", image_info
            
            # Do deep validation - try to transcode the image to verify data integrity
            # This will catch many issues that just loading the image won't
            try:
                output = io.BytesIO()
                img.save(output, format=img.format)
                
                # For JPEGs and BMPs, also verify by attempting to convert to PNG
                if img_type in ('jpeg', 'jpg', 'bmp'):
                    test_output = io.BytesIO()
                    img.save(test_output, format='PNG')
            except Exception as e:
                return False, f"Image transcode validation failed: {str(e)}", image_info
                
            return True, "", image_info
            
    except UnidentifiedImageError:
        return False, "Image data could not be identified as a valid image", {}
    except Exception as e:
        return False, f"Image validation error: {str(e)}", {}