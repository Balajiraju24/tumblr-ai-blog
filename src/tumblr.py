import time
import pytumblr
from typing import List, Dict, Any

from src.logger import setup_logger

logger = setup_logger("tumblr_client")

class TumblrClient:
    """Client for publishing posts to Tumblr using the pytumblr SDK."""

    def __init__(
        self,
        consumer_key: str,
        consumer_secret: str,
        oauth_token: str,
        oauth_token_secret: str,
        blog_name: str
    ):
        """Initializes the Tumblr API client and verifies configuration."""
        missing = []
        if not consumer_key:
            missing.append("TUMBLR_CONSUMER_KEY")
        if not consumer_secret:
            missing.append("TUMBLR_CONSUMER_SECRET")
        if not oauth_token:
            missing.append("TUMBLR_TOKEN")
        if not oauth_token_secret:
            missing.append("TUMBLR_TOKEN_SECRET")
        if not blog_name:
            missing.append("BLOG_NAME")

        if missing:
            raise ValueError(f"Missing required environment variables for Tumblr: {', '.join(missing)}")

        self.blog_name = blog_name
        try:
            # Initialize the pytumblr client
            self.client = pytumblr.TumblrRestClient(
                consumer_key,
                consumer_secret,
                oauth_token,
                oauth_token_secret
            )
        except Exception as e:
            logger.error(f"Failed to initialize pytumblr client: {e}")
            raise

    def publish_post(
        self,
        title: str,
        body: str,
        tags: List[str],
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Publishes a markdown post to Tumblr with retries.
        """
        logger.info("Tumblr upload started")
        
        attempt = 0
        while attempt < max_retries:
            attempt += 1
            logger.info(f"Uploading post to Tumblr (Attempt {attempt} of {max_retries})...")
            
            try:
                # Post to Tumblr API
                # By default, state="published" and format="markdown"
                response = self.client.create_text(
                    self.blog_name,
                    state="published",
                    format="markdown",
                    title=title,
                    body=body,
                    tags=tags
                )
                
                # Verify that Tumblr returned a success response containing a post ID
                # pytumblr usually returns a dict with details like {'id': 12345} or throws an error
                if response and isinstance(response, dict) and "id" in response:
                    logger.info(f"Tumblr upload completed successfully. Post ID: {response['id']}")
                    logger.info(f"Publish status: PUBLISHED on blog '{self.blog_name}'")
                    return response
                else:
                    raise RuntimeError(f"Unexpected response format from Tumblr: {response}")

            except Exception as e:
                logger.warning(f"Tumblr upload failed on attempt {attempt}: {e}")
                if attempt < max_retries:
                    sleep_time = 2 ** attempt
                    logger.info(f"Retrying upload in {sleep_time} seconds...")
                    time.sleep(sleep_time)
                else:
                    logger.error("All Tumblr upload attempts failed.")
                    raise

        raise RuntimeError(f"Failed to publish draft to Tumblr after {max_retries} attempts.")
