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

    def __init__(self, api_key: str = None, model_name: str = "gemini-2.0-flash"):
        """
        Initializes the Gemini Client.
        If api_key is None, it defaults to the GEMINI_API_KEY environment variable.
        """
        self.model_name = model_name
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set.")

    def _get_api_url(self, model: str) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def generate_post(
        self, 
        topic: str, 
        word_count_min: int = 800, 
        word_count_max: int = 1200, 
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Generates and parses a blog post on a given topic.
        Includes automatic model fallback (e.g. gemini-2.0-flash -> gemini-2.0-flash-lite) if 
        a model hits rate limits (429), high demand (503), or deprecation (404).
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

        # Define candidate models in priority order
        fallback_chain = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash-8b"]
        models_to_try = [self.model_name] + [m for m in fallback_chain if m != self.model_name]

        last_error = None
        for current_model in models_to_try:
            api_url = self._get_api_url(current_model)
            logger.info(f"Attempting generation with model: '{current_model}'")
            
            attempt = 0
            while attempt < max_retries:
                attempt += 1
                logger.info(f"Model [{current_model}] attempt {attempt} of {max_retries}...")
                
                try:
                    response = requests.post(
                        api_url, 
                        json=payload, 
                        params=params, 
                        headers=headers,
                        timeout=60
                    )
                    
                    # Check for rate limit / quota (429) or service unavailable (503)
                    if response.status_code in (429, 503, 404):
                        logger.warning(
                            f"Model [{current_model}] returned HTTP {response.status_code}: {response.text[:200]}"
                        )
                        # Switch to fallback model immediately if quota/503 error occurs
                        last_error = RuntimeError(f"HTTP {response.status_code} for model {current_model}")
                        break
                    
                    response.raise_for_status()
                    response_data = response.json()
                    
                    candidates = response_data.get("candidates", [])
                    if not candidates:
                        prompt_feedback = response_data.get("promptFeedback", {})
                        block_reason = prompt_feedback.get("blockReason")
                        if block_reason:
                            raise RuntimeError(f"Gemini API blocked the request. Reason: {block_reason}")
                        raise ParseError("Gemini API response did not contain candidates.")
                    
                    candidate = candidates[0]
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
                    
                    post_data["topic"] = topic
                    logger.info(f"AI generation completed successfully using model [{current_model}].")
                    return post_data

                except requests.exceptions.HTTPError as http_err:
                    logger.warning(f"HTTP error on model [{current_model}] attempt {attempt}: {http_err}")
                    last_error = http_err
                    if attempt < max_retries:
                        time.sleep(3)
                except requests.exceptions.RequestException as req_err:
                    logger.warning(f"Connection error on model [{current_model}] attempt {attempt}: {req_err}")
                    last_error = req_err
                    if attempt < max_retries:
                        time.sleep(3)
                except ParseError as parse_err:
                    logger.warning(f"Parsing failed on model [{current_model}] attempt {attempt}: {parse_err}")
                    last_error = parse_err
                    if attempt < max_retries:
                        time.sleep(2)
                except Exception as e:
                    logger.error(f"Unexpected error on model [{current_model}] attempt {attempt}: {e}")
                    last_error = e
                    if attempt < max_retries:
                        time.sleep(2)

            logger.warning(f"Model [{current_model}] failed after retries. Trying fallback model if available...")

        raise RuntimeError(f"Failed to generate a valid post across all models ({models_to_try}). Last error: {last_error}")
