import time
import os
import requests
from typing import Dict, Any
from google import genai
from google.genai import types
from google.genai.errors import APIError

from src.logger import setup_logger
from src.prompts import load_system_prompt, get_user_prompt
from src.parser import parse_post, ParseError

logger = setup_logger("gemini_client")

class GeminiClient:
    """Client for generating content using Google Gemini SDK with ChatGPT fallback support."""

    def __init__(self, api_key: str = None, model_name: str = "gemini-2.0-flash"):
        """
        Initializes the Gemini Client using the official google-genai SDK.
        If api_key is None, it defaults to the GEMINI_API_KEY environment variable.
        """
        self.model_name = model_name
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set.")

        self.client = genai.Client(api_key=self.api_key)

    def _generate_with_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        topic: str,
        word_count_min: int,
        word_count_max: int
    ) -> Dict[str, Any]:
        """Fallback method to generate blog posts using OpenAI ChatGPT models (default: gpt-4o-mini)."""
        openai_key = os.environ.get("OPENAI_API_KEY")
        if not openai_key:
            raise RuntimeError("OPENAI_API_KEY environment variable is not set.")

        configured_model = os.environ.get("OPENAI_MODEL")
        openai_models = [configured_model] if configured_model else ["gpt-4o-mini"]
        last_openai_err = None

        openai_user_prompt = (
            f"{user_prompt}\n\n"
            f"CRITICAL: The essay BODY must be at least {word_count_min} words and no more than {word_count_max} words. "
            f"Aim for ~950 words. Do not write a short summary."
        )

        for openai_model in openai_models:
            logger.info(f"Attempting fallback generation with ChatGPT model: '{openai_model}'")
            try:
                url = "https://api.openai.com/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": openai_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": openai_user_prompt}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 2500
                }
                response = requests.post(url, json=payload, headers=headers, timeout=60)
                response.raise_for_status()
                
                data = response.json()
                choices = data.get("choices", [])
                if not choices:
                    raise ParseError("OpenAI response did not contain choices.")
                    
                content = choices[0].get("message", {}).get("content", "")
                if not content.strip():
                    raise ParseError("OpenAI returned an empty message response.")

                post_data = parse_post(
                    content,
                    word_count_min=word_count_min,
                    word_count_max=word_count_max
                )
                post_data["topic"] = topic
                logger.info(f"AI generation completed successfully using ChatGPT model [{openai_model}].")
                return post_data
            except Exception as e:
                logger.warning(f"ChatGPT model [{openai_model}] failed: {e}")
                last_openai_err = e

        raise RuntimeError(f"Failed to generate post using ChatGPT models ({openai_models}). Last error: {last_openai_err}")

    def generate_post(
        self, 
        topic: str, 
        word_count_min: int = 500, 
        word_count_max: int = 700, 
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Generates and parses a blog post on a given topic using the official GenAI SDK.
        Includes automatic model fallback across Gemini models and ChatGPT models (if OPENAI_API_KEY is set).
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

        # Define candidate models supported by the Google GenAI API
        fallback_chain = [
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite"
        ]
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
                    
                    # If 429 (Quota Exceeded) or 404 (Not Found), switch to fallback model immediately
                    if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "404" in err_msg or "NOT_FOUND" in err_msg:
                        logger.warning(f"Model [{current_model}] quota or availability limit reached. Trying next fallback model...")
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

        # If all Gemini models fail, attempt ChatGPT fallback if OPENAI_API_KEY is available
        if os.environ.get("OPENAI_API_KEY"):
            logger.info("Gemini models unavailable/exhausted. Attempting fallback to ChatGPT models...")
            try:
                return self._generate_with_openai(
                    system_prompt, user_prompt, topic, word_count_min, word_count_max
                )
            except Exception as openai_err:
                logger.error(f"ChatGPT model fallback failed: {openai_err}")

        raise RuntimeError(
            f"Daily free API quota exhausted across all available Gemini models for today. "
            f"Quota will automatically reset at 00:00 UTC (10:00 AM AEST). Last error: {last_error}"
        )
