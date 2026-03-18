from typing import Optional, Any
import base64
import os
from constants import ISO_TO_DISPLAY

def get_iso_language_code(display_name: str) -> str:
    """Extract ISO code from 'Name (code)' format.
    
    Args:
        display_name: The display name of the language
        
    Returns:
        ISO code (e.g., 'en')
    """
    if not display_name or display_name == "":
        return "en"
    if "(" in display_name and display_name.endswith(")"):
        return display_name.split("(")[-1].rstrip(")")
    return display_name

def normalize_language_name(language_code: Optional[str]) -> str:
    """Convert various language codes/names to standard 'Name (code)' format."""
    if not language_code:
        return ""
    
    normalized = language_code.lower()
    
    # Handle full names returned by some Whisper implementations
    name_to_code = {
        "ukrainian": "uk", "english": "en", "arabic": "ar", "spanish": "es",
        "french": "fr", "german": "de", "bengali": "bn", "russian": "ru",
        "chinese": "zh", "japanese": "ja", "korean": "ko"
    }
    
    if normalized in name_to_code:
        normalized = name_to_code[normalized]
        
    return ISO_TO_DISPLAY.get(normalized, f"Unknown ({normalized})")

def encode_image_to_base64(image_path: str) -> str:
    """Convert local image to base64 string."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def check_logo_exists(path: str) -> Optional[str]:
    """Check if logo file exists."""
    return path if os.path.exists(path) else None

def to_str(val: Any) -> str:
    """Helper to convert list fields to comma-separated strings or handle None."""
    if isinstance(val, list):
        return ", ".join([str(item) for item in val if item])
    return str(val) if val is not None else "N/A"
