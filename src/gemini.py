import time
import os
from typing import Dict, Any
from google import genai
from google.genai import types
from google.genai.errors import APIError

from src.logger import setup_logger
from src.prompts import load_system_prompt, get_user_prompt
from src.parser import parse_post, ParseError

logger = setup_logger("gemini_client")

class GeminiClient:
    """Client for generating content using the official Google GenAI SDK."""

    def __init__(self, api_key: str = None, model_name: str = "gemini-2.5-flash"):
        """
        Initializes the Gemini Client using the official google-genai SDK.
        If api_key is None, it defaults to the GEMINI_API_KEY environment variable.
        """
        self.model_name = model_name
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set.")

        self.client = genai.Client(api_key=self.api_key)

    def generate_post(
        self, 
        topic: str, 
        word_count_min: int = 800, 
        word_count_max: int = 1200, 
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Generates and parses a blog post on a given topic using the official GenAI SDK.
        Includes automatic model fallback (gemini-2.5-flash -> gemini-2.0-flash -> gemini-1.5-flash).
        """
        logger.info(f"AI generation started for topic: '{topic}'")
        
        # Load system instructions
        try:
            system_prompt = load_system_prompt(
                word_count_min=word_count_min, 
                word_count_max=word_count_max
            )
        except Exception as e:
            logger.error(f"Failed to load system prompt: {e}")
            raise

        user_prompt = get_user_prompt(topic)

        # Define candidate models across Flash and Pro families to leverage separate quota pools
        fallback_chain = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-pro", "gemini-2.0-pro-exp-02-05"]
        models_to_try = [self.model_name] + [m for m in fallback_chain if m != self.model_name]

        last_error = None
        for current_model in models_to_try:
            logger.info(f"Attempting generation with model: '{current_model}'")
            
            attempt = 0
            while attempt < max_retries:
                attempt += 1
                logger.info(f"Model [{current_model}] attempt {attempt} of {max_retries}...")
                
                try:
                    config = types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=0.7,
                    )
                    
                    response = self.client.models.generate_content(
                        model=current_model,
                        contents=user_prompt,
                        config=config
                    )
                    
                    if not response.text or not response.text.strip():
                        raise ParseError("Gemini returned a response with no text content.")

                    # Parse and validate response
                    post_data = parse_post(
                        response.text, 
                        word_count_min=word_count_min, 
                        word_count_max=word_count_max
                    )
                    
                    post_data["topic"] = topic
                    logger.info(f"AI generation completed successfully using model [{current_model}].")
                    return post_data

                except APIError as api_err:
                    err_msg = str(api_err)
                    logger.warning(f"Google GenAI API error on model [{current_model}] attempt {attempt}: {err_msg[:250]}")
                    last_error = api_err
                    
                    # If 429 (Resource Exhausted / Quota Exceeded) or 404 (Not Found), switch to fallback model immediately
                    if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "404" in err_msg or "NOT_FOUND" in err_msg:
                        logger.warning(f"Model [{current_model}] quota/availability limit reached. Switching to next fallback model immediately...")
                        break
                    
                    # For 503 transient errors, pause briefly and retry current model
                    if attempt < max_retries:
                        logger.info("Waiting 10 seconds for service recovery...")
                        time.sleep(10)
                except ParseError as parse_err:
                    logger.warning(f"Parsing failed on model [{current_model}] attempt {attempt}: {parse_err}")
                    last_error = parse_err
                    if attempt < max_retries:
                        time.sleep(2)
                except Exception as e:
                    logger.error(f"Unexpected error on model [{current_model}] attempt {attempt}: {e}")
                    last_error = e
                    if attempt < max_retries:
                        time.sleep(3)

            logger.warning(f"Model [{current_model}] unavailable. Trying fallback model if available...")

        raise RuntimeError(f"Failed to generate a valid post across all models ({models_to_try}). Last error: {last_error}")
