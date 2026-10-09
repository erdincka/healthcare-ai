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


def normalize_language_name(language_code: str | None) -> str:
    """Convert various language codes/names to standard 'Name (code)' format."""
    if not language_code:
        return ""

    normalized = language_code.lower()

    # Handle full names returned by some Whisper implementations
    name_to_code = {
        "ukrainian": "uk",
        "english": "en",
        "arabic": "ar",
        "spanish": "es",
        "french": "fr",
        "german": "de",
        "bengali": "bn",
        "russian": "ru",
        "chinese": "zh",
        "japanese": "ja",
        "korean": "ko",
    }

    if normalized in name_to_code:
        normalized = name_to_code[normalized]

    return ISO_TO_DISPLAY.get(normalized, f"Unknown ({normalized})")


def encode_image_to_base64(image_path: str) -> str:
    """Convert local image to base64 string."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def check_logo_exists(path: str) -> str | None:
    """Check if logo file exists."""
    return path if os.path.exists(path) else None


def format_exception_details(e: Exception) -> str:
    """Format exception type and message into a detailed string, traversing the cause/context chain if needed."""
    msgs: list[str] = []
    curr: BaseException | None = e
    seen: set[int] = set()
    while curr and id(curr) not in seen:
        seen.add(id(curr))
        curr_name = type(curr).__name__
        curr_msg = str(curr).strip()
        if curr_msg:
            msgs.append(f"{curr_name}: {curr_msg}")
        else:
            msgs.append(curr_name)

        # Traverse down the chain
        if curr.__cause__:
            curr = curr.__cause__
        elif curr.__context__:
            curr = curr.__context__
        else:
            break

    # Clean up and deduplicate sequential identical messages
    unique_msgs: list[str] = []
    for msg in msgs:
        if not unique_msgs or unique_msgs[-1] != msg:
            unique_msgs.append(msg)

    return " -> ".join(unique_msgs)
