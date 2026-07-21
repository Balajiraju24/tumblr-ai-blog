import re
from typing import Dict, List, Any

class ParseError(ValueError):
    """Raised when the AI response does not match the required format or fails validation."""
    pass

def parse_post(text: str, word_count_min: int = 500, word_count_max: int = 750) -> Dict[str, Any]:
    """
    Parses a generated Tumblr post text and validates its components.
    
    Expected format:
    TITLE: <title>
    
    BODY: <body>
    
    TAGS:
    tag1, tag2, tag3, tag4, tag5
    """
    if not text:
        raise ParseError("Received empty text from AI model.")

    # Remove markdown code block fences if Gemini included them
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n", "", cleaned)
        cleaned = re.sub(r"\n```$", "", cleaned).strip()

    # Find the positions of key headers (case-insensitive)
    lower_text = cleaned.lower()
    title_marker = "title:"
    body_marker = "body:"
    tags_marker = "tags:"

    title_idx = lower_text.find(title_marker)
    body_idx = lower_text.find(body_marker)
    tags_idx = lower_text.find(tags_marker)

    # Validate that all markers exist in the correct order
    if title_idx == -1:
        raise ParseError("Missing 'TITLE:' marker in the generated post.")
    if body_idx == -1:
        raise ParseError("Missing 'BODY:' marker in the generated post.")
    if tags_idx == -1:
        raise ParseError("Missing 'TAGS:' marker in the generated post.")
    if not (title_idx < body_idx < tags_idx):
        raise ParseError(
            f"Markers are in the wrong order. Found TITLE at {title_idx}, "
            f"BODY at {body_idx}, and TAGS at {tags_idx}."
        )

    # Extract sections
    title = cleaned[title_idx + len(title_marker):body_idx].strip()
    body = cleaned[body_idx + len(body_marker):tags_idx].strip()
    tags_raw = cleaned[tags_idx + len(tags_marker):].strip()

    # Clean the extracted title
    # Remove markdown header markers if any (e.g. #, ##, **, etc.)
    title = title.strip("*_` ")
    title = re.sub(r"^#+\s*", "", title)
    title = title.strip("*_` ")

    # Validate Title
    if not title:
        raise ParseError("Extracted title is empty.")

    # Validate Body
    if not body:
        raise ParseError("Extracted body is empty.")

    # Calculate word count
    words = body.split()
    word_count = len(words)
    if word_count < word_count_min or word_count > word_count_max:
        raise ParseError(
            f"Body word count of {word_count} is out of bounds "
            f"({word_count_min} - {word_count_max} words)."
        )

    # Parse and clean tags
    # Tags can be on newlines or comma separated
    tags_list: List[str] = []
    # If the raw tags contain commas, split by commas
    if "," in tags_raw:
        parts = tags_raw.split(",")
    else:
        # Fallback: split by newlines or spaces
        parts = re.split(r"[\n\r]+", tags_raw)
        if len(parts) <= 1:
            parts = tags_raw.split()

    for part in parts:
        tag = part.strip()
        # Remove leading hashtags if any
        if tag.startswith("#"):
            tag = tag[1:].strip()
        if tag:
            tags_list.append(tag)

    if not tags_list:
        raise ParseError("No valid tags found in the 'TAGS:' section.")

    return {
        "title": title,
        "body": body,
        "tags": tags_list,
        "word_count": word_count
    }
