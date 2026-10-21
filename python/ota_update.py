"""
OTA firmware update over BLE with corruption protection.
Chunks written to a staging area; CRC verified before swap.
"""
import os
import hashlib
import machine

# Staging area for OTA chunks (preserved across resets)
_OTA_STAGING = "/ota_staging"
_OTA_MANIFEST = "/ota_manifest.txt"
_OTA_CHUNK_PREFIX = "chunk_"
_OTA_SWAP_FLAG = "/ota_swap_in_progress"

# Target files that can be updated
_UPDATEABLE_FILES = {
    "main.py": "/main.py",
    "phone_link.py": "/phone_link.py",
    "screens.py": "/screens.py",
    "render.py": "/render.py",
    "battery.py": "/battery.py",
}

def _ensure_staging():
    """Create staging directory if it doesn't exist."""
    try:
        os.stat(_OTA_STAGING)
    except OSError:
        try:
            os.mkdir(_OTA_STAGING)
        except OSError:
            pass

def _write_chunk(chunk_idx, data):
    """Write a single chunk to staging area."""
    _ensure_staging()
    path = "{}/{}{:04d}".format(_OTA_STAGING, _OTA_CHUNK_PREFIX, chunk_idx)
    try:
        with open(path, "wb") as f:
            f.write(data)
        return True
    except (OSError, IOError) as e:
        print("OTA: chunk write error:", e)
        return False

def _read_chunk(chunk_idx):
    """Read a single chunk from staging area."""
    path = "{}/{}{:04d}".format(_OTA_STAGING, _OTA_CHUNK_PREFIX, chunk_idx)
    try:
        with open(path, "rb") as f:
            return f.read()
    except (OSError, IOError):
        return None

def _cleanup_staging():
    """Remove all staged chunks."""
    try:
        import shutil
        shutil.rmtree(_OTA_STAGING)
    except (OSError, ImportError):
        # Fallback: delete files one by one
        try:
            for entry in os.listdir(_OTA_STAGING):
                path = "{}/{}".format(_OTA_STAGING, entry)
                try:
                    os.remove(path)
                except OSError:
                    pass
            os.rmdir(_OTA_STAGING)
        except OSError:
            pass

def begin_update(filename, total_bytes, expected_sha256):
    """
    Start a new OTA update session.
    filename: name of file to update (must be in _UPDATEABLE_FILES)
    total_bytes: total size in bytes
    expected_sha256: hex string of expected SHA256 of final binary

    Returns True if session started, False if filename not allowed or error.
    """
    if filename not in _UPDATEABLE_FILES:
        print("OTA: filename not updateable:", filename)
        return False

    _cleanup_staging()
    _ensure_staging()

    manifest = {
        "filename": filename,
        "total_bytes": total_bytes,
        "expected_sha256": expected_sha256,
        "chunks_received": 0,
        "bytes_received": 0,
    }

    try:
        with open(_OTA_MANIFEST, "w") as f:
            for key, val in manifest.items():
                f.write("{}={}\n".format(key, val))
        print("OTA: update session begun for", filename)
        return True
    except (OSError, IOError) as e:
        print("OTA: manifest write error:", e)
        return False

def add_chunk(chunk_idx, data):
    """
    Add a data chunk to the update.
    chunk_idx: 0-based chunk number
    data: bytes of chunk

    Returns True if accepted, False on error.
    """
    try:
        with open(_OTA_MANIFEST, "r") as f:
            manifest_text = f.read()
    except (OSError, IOError):
        print("OTA: no active update session")
        return False

    if not _write_chunk(chunk_idx, data):
        return False

    # Update manifest
    lines = manifest_text.strip().split("\n")
    manifest = {}
    for line in lines:
        if "=" in line:
            key, val = line.split("=", 1)
            manifest[key.strip()] = val.strip()

    manifest["chunks_received"] = str(int(manifest.get("chunks_received", 0)) + 1)
    manifest["bytes_received"] = str(int(manifest.get("bytes_received", 0)) + len(data))

    try:
        with open(_OTA_MANIFEST, "w") as f:
            for key, val in manifest.items():
                f.write("{}={}\n".format(key, val))
        return True
    except (OSError, IOError) as e:
        print("OTA: manifest update error:", e)
        return False

def finalize_update():
    """
    Finalize the update: reassemble chunks, verify SHA256, swap files.

    Returns (success, message) tuple.
    """
    try:
        with open(_OTA_MANIFEST, "r") as f:
            manifest_text = f.read()
    except (OSError, IOError):
        return (False, "no active update")

    lines = manifest_text.strip().split("\n")
    manifest = {}
    for line in lines:
        if "=" in line:
            key, val = line.split("=", 1)
            manifest[key.strip()] = val.strip()

    filename = manifest.get("filename")
    total_bytes = int(manifest.get("total_bytes", 0))
    expected_sha256 = manifest.get("expected_sha256", "").lower()

    if not filename or not total_bytes:
        return (False, "invalid manifest")

    # Reassemble chunks in order
    reassembled = bytearray()
    chunk_idx = 0
    while True:
        chunk = _read_chunk(chunk_idx)
        if chunk is None:
            break
        reassembled.extend(chunk)
        chunk_idx += 1

    if len(reassembled) != total_bytes:
        return (False, "size mismatch: {} vs {}".format(len(reassembled), total_bytes))

    # Verify SHA256
    actual_sha256 = hashlib.sha256(bytes(reassembled)).hexdigest().lower()
    if actual_sha256 != expected_sha256:
        return (False, "SHA256 mismatch: {} vs {}".format(actual_sha256, expected_sha256))

    # Atomically replace target file
    target_path = _UPDATEABLE_FILES[filename]
    backup_path = target_path + ".bak"

    try:
        # Write swap-in-progress flag before any file operations
        try:
            with open(_OTA_SWAP_FLAG, "w") as f:
                f.write("filename={}\n".format(filename))
        except (OSError, IOError) as e:
            print("OTA: failed to write swap flag:", e)
            return (False, "cannot write swap flag")

        # Backup current file
        try:
            with open(target_path, "rb") as src:
                with open(backup_path, "wb") as dst:
                    dst.write(src.read())
        except (OSError, IOError):
            pass  # No backup if original doesn't exist

        # Write new file
        with open(target_path, "wb") as f:
            f.write(bytes(reassembled))

        # If we get here, swap succeeded — clear the flag
        try:
            os.remove(_OTA_SWAP_FLAG)
        except OSError:
            pass

        _cleanup_staging()
        try:
            os.remove(_OTA_MANIFEST)
        except OSError:
            pass

        print("OTA: {} updated successfully".format(filename))
        return (True, "update complete")

    except (OSError, IOError) as e:
        # Swap failed — try to restore from backup (if it exists)
        try:
            if os.stat(backup_path):
                with open(backup_path, "rb") as src:
                    with open(target_path, "wb") as dst:
                        dst.write(src.read())
                print("OTA: restored backup for", filename)
        except OSError:
            pass

        # Clear the flag so boot doesn't try to restore again
        try:
            os.remove(_OTA_SWAP_FLAG)
        except OSError:
            pass

        return (False, "write error: {}".format(e))

def cancel_update():
    """Discard an in-progress update."""
    _cleanup_staging()
    try:
        os.remove(_OTA_MANIFEST)
    except OSError:
        pass
    print("OTA: update cancelled")

def get_update_status():
    """Get status of current update, or None if none in progress."""
    try:
        with open(_OTA_MANIFEST, "r") as f:
            manifest_text = f.read()
    except (OSError, IOError):
        return None

    lines = manifest_text.strip().split("\n")
    manifest = {}
    for line in lines:
        if "=" in line:
            key, val = line.split("=", 1)
            manifest[key.strip()] = val.strip()

    return {
        "filename": manifest.get("filename"),
        "total_bytes": int(manifest.get("total_bytes", 0)),
        "bytes_received": int(manifest.get("bytes_received", 0)),
        "progress_pct": int(100 * int(manifest.get("bytes_received", 0)) / max(1, int(manifest.get("total_bytes", 1)))),
    }

def check_for_pending_update():
    """
    At boot, check if an update was interrupted or failed.
    If swap flag exists, restore backup and clear flag.
    If staged chunks exist but update wasn't finalized, warn.
    Returns True if recovery/warning needed (user should check result).
    """
    # Check for interrupted swap (crash mid-update)
    try:
        with open(_OTA_SWAP_FLAG, "r") as f:
            flag_text = f.read()
        lines = flag_text.strip().split("\n")
        flag_data = {}
        for line in lines:
            if "=" in line:
                key, val = line.split("=", 1)
                flag_data[key.strip()] = val.strip()

        filename = flag_data.get("filename")
        if filename in _UPDATEABLE_FILES:
            target_path = _UPDATEABLE_FILES[filename]
            backup_path = target_path + ".bak"

            # Restore from backup
            try:
                with open(backup_path, "rb") as src:
                    with open(target_path, "wb") as dst:
                        dst.write(src.read())
                print("OTA: recovered from failed swap, restored", filename)
            except (OSError, IOError) as e:
                print("OTA: recovery failed:", e)
            finally:
                # Clear the flag
                try:
                    os.remove(_OTA_SWAP_FLAG)
                except OSError:
                    pass

        return True
    except (OSError, IOError):
        pass  # No swap flag, continue

    # Check for incomplete update (chunks staged but not finalized)
    status = get_update_status()
    if status is None:
        return False

    print("OTA: found pending update for {}: {}/{} bytes".format(
        status["filename"],
        status["bytes_received"],
        status["total_bytes"]
    ))
    return True
