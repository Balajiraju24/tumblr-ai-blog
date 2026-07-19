import time
import os
import requests
from typing import Dict, Any

from src.logger import setup_logger
from src.prompts import load_system_prompt, get_user_prompt
from src.parser import parse_post, ParseError

logger = setup_logger("gemini_client")

class GeminiClient:
    """Client for generating content using the Google Gemini REST API directly."""

    def __init__(self, api_key: str = None, model_name: str = "gemini-3.5-flash"):
        """
        Initializes the Gemini Client.
        If api_key is None, it defaults to the GEMINI_API_KEY environment variable.
        """
        self.model_name = model_name
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set.")
            
        # Define API URL for Gemini generateContent
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"

    def generate_post(
        self, 
        topic: str, 
        word_count_min: int = 800, 
        word_count_max: int = 1200, 
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Generates and parses a blog post on a given topic, with up to `max_retries` attempts.
        Calls the REST endpoint directly and handles API and safety block errors.
        """
        logger.info(f"AI generation started for topic: '{topic}'")
        
        # Load the system instructions
        try:
            system_prompt = load_system_prompt(
                word_count_min=word_count_min, 
                word_count_max=word_count_max
            )
        except Exception as e:
            logger.error(f"Failed to load system prompt: {e}")
            raise

        user_prompt = get_user_prompt(topic)

        # Build payload according to the Gemini API JSON structure
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": user_prompt}
                    ]
                }
            ],
            "systemInstruction": {
                "parts": [
                    {"text": system_prompt}
                ]
            },
            "generationConfig": {
                "temperature": 0.7
            }
        }

        params = {"key": self.api_key}
        headers = {"Content-Type": "application/json"}

        attempt = 0
        while attempt < max_retries:
            attempt += 1
            logger.info(f"Generation attempt {attempt} of {max_retries}...")
            
            try:
                # Call Gemini API via requests
                response = requests.post(
                    self.api_url, 
                    json=payload, 
                    params=params, 
                    headers=headers,
                    timeout=30
                )
                
                # Check HTTP errors
                response.raise_for_status()
                
                response_data = response.json()
                
                # Extract candidates
                candidates = response_data.get("candidates", [])
                if not candidates:
                    # Check if response was blocked by safety filters
                    prompt_feedback = response_data.get("promptFeedback", {})
                    block_reason = prompt_feedback.get("blockReason")
                    if block_reason:
                        raise RuntimeError(f"Gemini API blocked the request. Reason: {block_reason}")
                    raise ParseError("Gemini API response did not contain candidates.")
                
                candidate = candidates[0]
                
                # Check for finish reason and block warnings
                finish_reason = candidate.get("finishReason")
                if finish_reason == "SAFETY":
                    raise RuntimeError("Gemini API generated response was blocked by safety settings.")
                elif finish_reason == "RECITATION":
                    raise RuntimeError("Gemini API generated response was blocked due to recitation check.")
                
                content = candidate.get("content", {})
                parts = content.get("parts", [])
                if not parts or "text" not in parts[0]:
                    raise ParseError("Candidate did not contain valid text parts.")
                
                generated_text = parts[0]["text"]
                if not generated_text.strip():
                    raise ParseError("Gemini returned a response with no text content.")

                # Parse and validate the response
                post_data = parse_post(
                    generated_text, 
                    word_count_min=word_count_min, 
                    word_count_max=word_count_max
                )
                
                # Add topic metadata
                post_data["topic"] = topic
                
                logger.info(f"AI generation completed successfully on attempt {attempt}.")
                return post_data

            except requests.exceptions.HTTPError as http_err:
                logger.warning(
                    f"Gemini API HTTP error on attempt {attempt}: {http_err} "
                    f"Response: {response.text}"
                )
                if attempt < max_retries:
                    sleep_time = 2 ** attempt
                    logger.info(f"Retrying in {sleep_time} seconds...")
                    time.sleep(sleep_time)
            except requests.exceptions.RequestException as req_err:
                logger.warning(f"Gemini API connection error on attempt {attempt}: {req_err}")
                if attempt < max_retries:
                    sleep_time = 2 ** attempt
                    logger.info(f"Retrying in {sleep_time} seconds...")
                    time.sleep(sleep_time)
            except ParseError as parse_err:
                logger.warning(f"Parsing/Validation failed on attempt {attempt}: {parse_err}")
                if attempt < max_retries:
                    logger.info("Retrying generation...")
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Unexpected error during generation on attempt {attempt}: {e}")
                if attempt < max_retries:
                    time.sleep(2)
                else:
                    raise

        raise RuntimeError(f"Failed to generate a valid post after {max_retries} attempts.")
