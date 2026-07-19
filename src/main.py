import os
import sys
import hashlib
import re
from datetime import datetime
from dotenv import load_dotenv

from src.logger import setup_logger
from src.prompts import get_random_topic
from src.gemini import GeminiClient
from src.tumblr import TumblrClient

# Load .env file for local development
load_dotenv()

logger = setup_logger("main_orchestrator")

HASHES_FILE = "published_hashes.txt"

def load_published_hashes() -> set:
    """Loads previously published post hashes to prevent duplicates."""
    if os.path.exists(HASHES_FILE):
        try:
            with open(HASHES_FILE, "r", encoding="utf-8") as f:
                return {line.strip() for line in f if line.strip()}
        except Exception as e:
            logger.error(f"Failed to read published hashes file: {e}")
            return set()
    return set()

def save_published_hash(content_hash: str) -> None:
    """Appends a new content hash to the record of published posts."""
    try:
        with open(HASHES_FILE, "a", encoding="utf-8") as f:
            f.write(f"{content_hash}\n")
        logger.info(f"Recorded post hash: {content_hash}")
    except Exception as e:
        logger.error(f"Failed to write content hash to {HASHES_FILE}: {e}")

def archive_post(title: str, body: str, topic: str, tags: list, content_hash: str) -> str:
    """Saves the generated post as a Markdown file in the archive/ directory."""
    try:
        os.makedirs("archive", exist_ok=True)
        # Create a URL/Filename friendly slug from the topic
        safe_topic = re.sub(r"[^a-zA-Z0-9_-]", "_", topic.lower().replace(" ", "_"))
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        filename = f"archive/{timestamp}_{safe_topic}.md"
        
        # Build frontmatter and content structure
        content = (
            f"---\n"
            f"title: {title}\n"
            f"date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"topic: {topic}\n"
            f"tags: {', '.join(tags)}\n"
            f"hash: {content_hash}\n"
            f"---\n\n"
            f"# {title}\n\n"
            f"{body}\n"
        )
        
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
            
        logger.info(f"Successfully saved post locally to: {filename}")
        return filename
    except Exception as e:
        logger.error(f"Failed to save post to archive: {e}")
        raise

def main():
    logger.info("Tumblr AI Auto Publisher pipeline starting")
    
    # 1. Read and validate environment configuration
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key:
        logger.error("Environment validation failed: GEMINI_API_KEY is not set.")
        sys.exit(1)

    # Tumblr config is only mandatory if NOT in dry-run mode
    dry_run_env = os.environ.get("DRY_RUN", "false").lower()
    is_dry_run = dry_run_env in ("true", "yes", "1")
    
    if is_dry_run:
        logger.info("DRY_RUN mode is active. Post will be generated and archived, but NOT published to Tumblr.")
    
    tumblr_consumer_key = os.environ.get("TUMBLR_CONSUMER_KEY")
    tumblr_consumer_secret = os.environ.get("TUMBLR_CONSUMER_SECRET")
    tumblr_token = os.environ.get("TUMBLR_TOKEN")
    tumblr_token_secret = os.environ.get("TUMBLR_TOKEN_SECRET")
    blog_name = os.environ.get("BLOG_NAME")

    if not is_dry_run:
        missing_tumblr = []
        if not tumblr_consumer_key: missing_tumblr.append("TUMBLR_CONSUMER_KEY")
        if not tumblr_consumer_secret: missing_tumblr.append("TUMBLR_CONSUMER_SECRET")
        if not tumblr_token: missing_tumblr.append("TUMBLR_TOKEN")
        if not tumblr_token_secret: missing_tumblr.append("TUMBLR_TOKEN_SECRET")
        if not blog_name: missing_tumblr.append("BLOG_NAME")
        
        if missing_tumblr:
            logger.error(f"Environment validation failed: Missing required Tumblr variables: {', '.join(missing_tumblr)}")
            sys.exit(1)

    # Configuration values
    word_count_min = int(os.environ.get("WORD_COUNT_MIN", "800"))
    word_count_max = int(os.environ.get("WORD_COUNT_MAX", "1200"))
    model_name = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

    # 2. Determine Topic
    # Check if a specific topic was requested manually
    manual_topic = os.environ.get("MANUAL_TOPIC")
    if manual_topic and manual_topic.strip():
        topic = manual_topic.strip()
        logger.info(f"Using manually specified topic: '{topic}'")
    else:
        topic = get_random_topic()
        logger.info(f"Selected random topic: '{topic}'")

    # 3. Initialize Gemini Client
    try:
        gemini_client = GeminiClient(api_key=gemini_api_key, model_name=model_name)
    except Exception as e:
        logger.error(f"Abort: Failed to initialize Gemini Client: {e}")
        sys.exit(1)

    # 4. Generate unique content and parse response
    published_hashes = load_published_hashes()
    post_data = None
    
    # Try up to 3 times to generate a post that doesn't duplicate existing content hashes
    for attempt in range(1, 4):
        logger.info(f"Post uniqueness check - attempt {attempt} of 3...")
        try:
            candidate_post = gemini_client.generate_post(
                topic=topic,
                word_count_min=word_count_min,
                word_count_max=word_count_max
            )
            
            # Hash body to verify uniqueness
            body_text = candidate_post["body"].strip()
            content_hash = hashlib.sha256(body_text.encode("utf-8")).hexdigest()
            
            if content_hash not in published_hashes:
                post_data = candidate_post
                post_data["hash"] = content_hash
                break
            else:
                logger.warning(
                    f"Attempt {attempt}: Generated post is a duplicate of a previously published post. "
                    f"Hash: {content_hash}."
                )
        except Exception as e:
            logger.error(f"Attempt {attempt} failed during unique content generation: {e}")
            if attempt == 3:
                logger.error("Failed to generate a valid post after 3 attempts. Exiting.")
                sys.exit(1)

    if not post_data:
        logger.error("Failed to generate a unique post after 3 attempts due to duplicate content hashes. Exiting.")
        sys.exit(1)

    # 5. Archive the generated post locally
    try:
        archive_post(
            title=post_data["title"],
            body=post_data["body"],
            topic=post_data["topic"],
            tags=post_data["tags"],
            content_hash=post_data["hash"]
        )
    except Exception as e:
        logger.warning(f"Non-critical failure: Post could not be saved to archive folder: {e}")

    # 6. Publish to Tumblr (if not in dry-run mode)
    if is_dry_run:
        logger.info("Dry-run execution completed. Content successfully generated and archived.")
        sys.exit(0)

    try:
        tumblr_client = TumblrClient(
            consumer_key=tumblr_consumer_key,
            consumer_secret=tumblr_consumer_secret,
            oauth_token=tumblr_token,
            oauth_token_secret=tumblr_token_secret,
            blog_name=blog_name
        )
        
        # Publish
        tumblr_client.publish_post(
            title=post_data["title"],
            body=post_data["body"],
            tags=post_data["tags"]
        )
        
        # Record the successful post hash
        save_published_hash(post_data["hash"])
        logger.info("Tumblr AI Auto Publisher pipeline completed successfully.")
        
    except Exception as e:
        logger.error(f"Pipeline crashed due to Tumblr upload error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
