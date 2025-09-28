"""Personal AI Newsletter Generator

A sophisticated newsletter generation system that learns your interests,
curates content from around the web, and sends personalized newsletters.
"""

__version__ = "0.1.0"
__author__ = "Personal AI Newsletter"
__email__ = "newsletter@yourdomain.com"

from src.models.state import NewsletterGenerationState
from src.models.content import ContentItem, CuratedNewsletter
from src.models.user import UserProfile

__all__ = [
    "NewsletterGenerationState",
    "ContentItem",
    "CuratedNewsletter",
    "UserProfile",
]