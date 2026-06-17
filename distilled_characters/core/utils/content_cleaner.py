"""Content cleaning utilities — strip HTML/CSS junk from crawled text."""
from __future__ import annotations

import re

# Lines matching only these patterns are removed (web/CSS junk).
# Be conservative: don't strip single-word lines (could be valid content).
_CSS_SELECTOR_LINE = re.compile(
    r'^\s*\.?[\w_-]+\s*(?:[>+~]\s*\.?[\w_-]+\s*)+$'  # .foo > .bar, .a+.b
)
_CLASS_NAME_LINE = re.compile(
    r'^\s*\.[a-zA-Z_][\w_-]*\s*$'  # .classname only
)


def clean_content(text: str) -> str:
    """Strip HTML, CSS, and common web scraping artifacts from text.

    Conservative: only removes obvious CSS patterns, not valid prose.
    """
    if not text:
        return ""

    # Remove CSS blocks: anything between { and } (CSS rules)
    text = re.sub(r'\{[^{}]*\}', ' ', text)

    # Remove class names with underscores and dots (.__page_content__, etc.)
    text = re.sub(r'\.\w+(?:__\w+)+', ' ', text)

    # Remove standalone CSS property-value pairs (not inside braces anymore)
    text = re.sub(
        r'\b(?:margin|padding|font-family|font-size|line-height|color|background|'
        r'display|position|width|height|max-width|min-height|border|'
        r'text-size-adjust|outline|box-sizing|user-select|hyphens|word-break|'
        r'text-decoration|list-style|overflow|visibility|font-weight|'
        r'margin-bottom|text-align|opacity)\s*:\s*[^;"\n]*;?',
        '', text, flags=re.IGNORECASE)

    # Remove HTML/XML tags
    text = re.sub(r'<[^>]+>', ' ', text)

    # Replace HTML entities
    entities = {
        '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"',
        '&#x27;': "'", '&#39;': "'", '&nbsp;': ' ',
        '&ldquo;': '"', '&rdquo;': '"', '&mdash;': '--', '&ndash;': '-',
        '&hellip;': '...', '&rsquo;': "'", '&lsquo;': "'",
    }
    for entity, replacement in entities.items():
        text = text.replace(entity, replacement)

    # Remove lines that are bare CSS class names (no selectors/combinators)
    text = re.sub(r'^\s*\.[a-zA-Z_][\w_-]*\s*$', '', text, flags=re.MULTILINE)
    # Remove lines that are CSS selectors WITH combinators: .foo > .bar, .a+.b.c
    # (these always have multiple class parts joined by combinators)
    text = re.sub(r'^\s*\.?[\w_-]+\s*(?:[>+~]\s*\.?[\w_-]+\s*)+\s*$', '', text, flags=re.MULTILINE)

    # Collapse whitespace
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
    text = re.sub(r'[ \t]{3,}', '  ', text)

    return text.strip()


def is_usable_content(text: str, min_length: int = 50) -> bool:
    """Check if content has enough meaningful text after cleaning."""
    cleaned = clean_content(text)
    # Count Chinese characters individually
    chinese = len(re.findall(r'[一-鿿＀-￯]', cleaned))
    # Count English by character too (not by word), for fairness
    english_chars = len(re.findall(r'[a-zA-Z]', cleaned))
    digits = len(re.findall(r'[0-9]', cleaned))
    # Total meaningful characters
    return (chinese + english_chars + digits) >= min_length
