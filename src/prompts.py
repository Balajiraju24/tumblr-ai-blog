import os
import random
from datetime import datetime
from typing import List, Tuple

# Default list of topics for post rotation
DEFAULT_TOPICS = [
    "scuba diving",
    "travel",
    "productivity",
    "observations about life",
    "hiking"
]

def get_random_topic(topics: List[str] = None) -> str:
    """Selects a random topic from the provided list or the default list."""
    if not topics:
        topics = DEFAULT_TOPICS
    return random.choice(topics)

def load_system_prompt(filepath: str = "prompts/system_prompt.txt", word_count_min: int = 500, word_count_max: int = 750) -> str:
    """
    Loads and formats the system prompt template from a file.
    Default parameters are applied if the template includes placeholder formatting.
    """
    # Look up prompt template relative to project root
    if not os.path.exists(filepath):
        # Try finding it relative to current working directory
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        possible_path = os.path.join(project_root, filepath)
        if os.path.exists(possible_path):
            filepath = possible_path
        else:
            raise FileNotFoundError(f"System prompt file not found at {filepath}")
            
    with open(filepath, "r", encoding="utf-8") as f:
        template = f.read()
        
    return template.format(word_count_min=word_count_min, word_count_max=word_count_max)

def get_user_prompt(topic: str, date_str: str = None) -> str:
    """Generates the user prompt detailing the topic and date for model generation."""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
        
    return (
        f"Today is {date_str}. Write a deeply engaging, personal essay or reflective post "
        f"on the topic: '{topic}'. Keep the writing original, authentic, and reflective. "
        f"Strictly follow the output format (TITLE, BODY, and TAGS) specified in your system instruction."
    )
