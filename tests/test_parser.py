import pytest
from src.parser import parse_post, ParseError

def test_parse_post_valid_format():
    sample_text = """
TITLE: Reflective Observations about Life

BODY:
This is a paragraph about observations of life. It should be long enough.
We will duplicate this sentence to make sure we hit the word count limit if needed.
But for testing specific word bounds, we can configure them.
Here is some more content to increase the length of the body.
Let's see if the word count is counted correctly by our splits.
This is another line of text.

TAGS:
life, reflections, observations, thoughts, philosophy
"""
    # Using small word count bounds to make tests easier to write
    parsed = parse_post(sample_text, word_count_min=10, word_count_max=100)
    
    assert parsed["title"] == "Reflective Observations about Life"
    assert "This is a paragraph" in parsed["body"]
    assert "observations of life" in parsed["body"]
    assert parsed["tags"] == ["life", "reflections", "observations", "thoughts", "philosophy"]
    assert parsed["word_count"] > 10

def test_parse_post_removes_code_block_fences():
    sample_text = """```text
TITLE: Markdown Title

BODY:
This is a post body wrapped inside markdown code block fences.
We want to verify that the parser strips the markdown markers correctly.
It should find the title, body, and tags without any issues.

TAGS:
markdown, formatting, clean
```"""
    parsed = parse_post(sample_text, word_count_min=5, word_count_max=50)
    assert parsed["title"] == "Markdown Title"
    assert parsed["tags"] == ["markdown", "formatting", "clean"]

def test_parse_post_removes_header_hashes_and_asterisks():
    sample_text = """
TITLE: **# Bold Title With Hash**

BODY:
This is the body of the post.

TAGS:
tags, header, clean
"""
    parsed = parse_post(sample_text, word_count_min=2, word_count_max=20)
    assert parsed["title"] == "Bold Title With Hash"

def test_parse_post_word_count_too_short():
    sample_text = """
TITLE: Too Short Post

BODY:
Only five words here today.

TAGS:
short, test
"""
    with pytest.raises(ParseError) as exc_info:
        # Minimum word count is 10, but post body only has 5 words
        parse_post(sample_text, word_count_min=10, word_count_max=50)
    assert "word count" in str(exc_info.value)
    assert "out of bounds" in str(exc_info.value)

def test_parse_post_word_count_too_long():
    sample_text = """
TITLE: Too Long Post

BODY:
This body has exactly ten words to test the limit.

TAGS:
long, test
"""
    with pytest.raises(ParseError) as exc_info:
        # Maximum word count is 5, but post body has 10 words
        parse_post(sample_text, word_count_min=2, word_count_max=5)
    assert "word count" in str(exc_info.value)

def test_parse_post_missing_markers():
    # Missing TITLE:
    sample_no_title = """
BODY:
Body content.

TAGS:
tag1, tag2
"""
    with pytest.raises(ParseError) as exc_info:
        parse_post(sample_no_title, word_count_min=1, word_count_max=10)
    assert "Missing 'TITLE:' marker" in str(exc_info.value)

    # Missing BODY:
    sample_no_body = """
TITLE: The Title

TAGS:
tag1, tag2
"""
    with pytest.raises(ParseError) as exc_info:
        parse_post(sample_no_body, word_count_min=1, word_count_max=10)
    assert "Missing 'BODY:' marker" in str(exc_info.value)

    # Missing TAGS:
    sample_no_tags = """
TITLE: The Title

BODY:
Body content here.
"""
    with pytest.raises(ParseError) as exc_info:
        parse_post(sample_no_tags, word_count_min=1, word_count_max=10)
    assert "Missing 'TAGS:' marker" in str(exc_info.value)

def test_parse_post_wrong_order():
    sample_wrong_order = """
BODY:
Some body first.

TITLE:
Then title.

TAGS:
tag1, tag2
"""
    with pytest.raises(ParseError) as exc_info:
        parse_post(sample_wrong_order, word_count_min=1, word_count_max=10)
    assert "Markers are in the wrong order" in str(exc_info.value)

def test_parse_post_strips_hashtags():
    sample_text = """
TITLE: Clean Tags Test

BODY:
Some body paragraphs are here.

TAGS:
#scubadiving, #travel, #australia
"""
    parsed = parse_post(sample_text, word_count_min=1, word_count_max=20)
    assert parsed["tags"] == ["scubadiving", "travel", "australia"]

def test_parse_post_whitespace_and_newline_tags():
    sample_text = """
TITLE: Newline Tags Test

BODY:
Some body paragraphs are here.

TAGS:
scubadiving
travel
australia
"""
    parsed = parse_post(sample_text, word_count_min=1, word_count_max=20)
    assert parsed["tags"] == ["scubadiving", "travel", "australia"]
