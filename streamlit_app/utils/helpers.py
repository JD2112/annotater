"""Helper utility functions"""

import os
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from ..config import Settings


def format_file_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format
    
    Args:
        size_bytes: Size in bytes
        
    Returns:
        Formatted string (e.g., "1.5 MB")
    """
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def estimate_memory(file_size_mb: float, multiplier: float = 5.0) -> str:
    """
    Estimate memory requirements
    
    Rule of thumb: processing requires ~5x file size in memory
    
    Args:
        file_size_mb: File size in megabytes
        multiplier: Memory multiplier (default: 5.0)
        
    Returns:
        Estimated memory as formatted string
    """
    estimated_mb = file_size_mb * multiplier
    return format_file_size(int(estimated_mb * 1024 * 1024))


def cleanup_temp_files(temp_dir: Optional[Path] = None, max_age_hours: Optional[int] = None):
    """
    Clean up old temporary files
    
    Args:
        temp_dir: Temporary directory to clean (uses Settings default if None)
        max_age_hours: Maximum file age in hours (uses Settings default if None)
    """
    if temp_dir is None:
        temp_dir = Settings.TEMP_DIR
    
    if max_age_hours is None:
        max_age_hours = Settings.CLEANUP_AFTER_HOURS
    
    if not temp_dir.exists():
        return
    
    cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
    
    for item in temp_dir.iterdir():
        try:
            # Get file modification time
            mtime = datetime.fromtimestamp(item.stat().st_mtime)
            
            # Delete if older than cutoff
            if mtime < cutoff_time:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
        except Exception:
            # Skip files that can't be deleted
            pass


def save_uploaded_file(uploaded_file, destination_dir: Optional[Path] = None) -> Path:
    """
    Write an uploaded file to a safe, unique temporary path and return it.
    
    The path is a random token under the configured temp dir, suffixed with
    ONLY the extension of the uploaded name (kept because format detection
    reads it). The user-supplied filename itself never appears in the
    filesystem path and cannot influence it: path separators and other
    components are discarded, and the random token makes two same-named
    uploads distinct instead of colliding on one path.
    
    The caller owns the lifecycle: the returned path MUST be deleted as
    soon as the file no longer needs to exist on disk (the app deletes it
    immediately after parsing, whether parsing succeeds or fails).
    
    Args:
        uploaded_file: Streamlit uploaded file object (anything with
            .name and .getvalue())
        destination_dir: Directory to save to (uses Settings TEMP_DIR if None)
        
    Returns:
        Path to saved file
    """
    if destination_dir is None:
        destination_dir = Settings.ensure_temp_dir()
    
    suffix = Path(uploaded_file.name).suffix
    fd, filepath = tempfile.mkstemp(
        prefix="upload_", suffix=suffix, dir=destination_dir
    )
    
    with os.fdopen(fd, "wb") as f:
        f.write(uploaded_file.getvalue())
    
    return Path(filepath)


def get_example_data_path(filename: str) -> Path:
    """
    Get path to example data file
    
    Args:
        filename: Example filename
        
    Returns:
        Path to example file
    """
    # Assuming examples are in data/examples/
    return Path(__file__).parent.parent.parent / "data" / "examples" / filename
