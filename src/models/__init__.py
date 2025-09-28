"""Data models for the Personal AI Newsletter Generator."""

from .state import NewsletterGenerationState, ProcessingError, GenerationRequest
from .content import ContentItem, AnalyzedContent, CuratedNewsletter, ContentSource
from .user import UserProfile, UserInteraction, DeliveryResult
from .email import EmailContent, TemplateData

__all__ = [
    "NewsletterGenerationState",
    "ProcessingError",
    "GenerationRequest",
    "ContentItem",
    "AnalyzedContent",
    "CuratedNewsletter",
    "ContentSource",
    "UserProfile",
    "UserInteraction",
    "DeliveryResult",
    "EmailContent",
    "TemplateData",
]