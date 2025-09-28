"""Database management and models for the Personal AI Newsletter Generator."""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, AsyncIterator

from sqlalchemy import (
    Column, String, DateTime, Float, Integer, Text, Boolean,
    ForeignKey, JSON, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, selectinload
from sqlalchemy.sql import select, update, delete
from sqlalchemy import func

from src.infrastructure.config import ApplicationConfig

Base = declarative_base()


class User(Base):
    """User model for newsletter subscribers."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    timezone = Column(String(50), default="UTC", nullable=False)
    github_username = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    interests = relationship("UserInterest", back_populates="user", cascade="all, delete-orphan")
    deliveries = relationship("NewsletterDelivery", back_populates="user", cascade="all, delete-orphan")
    interactions = relationship("UserInteraction", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email})>"


class UserInterest(Base):
    """User interests and their weights."""

    __tablename__ = "user_interests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    interest = Column(String(255), nullable=False)
    weight = Column(Float, default=1.0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="interests")

    # Constraints
    __table_args__ = (
        UniqueConstraint("user_id", "interest", name="unique_user_interest"),
        Index("idx_user_interests_user_id", "user_id"),
    )


class ContentItem(Base):
    """Content items collected from various sources."""

    __tablename__ = "content_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(500), nullable=False)
    url = Column(String(1000), nullable=False, index=True)
    source = Column(String(255), nullable=False)
    content_type = Column(String(50), nullable=False)
    summary = Column(Text, nullable=True)
    author = Column(String(255), nullable=True)
    published_at = Column(DateTime, nullable=True)
    relevance_score = Column(Float, default=0.0, nullable=False)
    click_count = Column(Integer, default=0, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    item_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    interactions = relationship("UserInteraction", back_populates="content_item")

    # Constraints
    __table_args__ = (
        Index("idx_content_items_source", "source"),
        Index("idx_content_items_published", "published_at"),
        Index("idx_content_items_relevance", "relevance_score"),
    )


class NewsletterDelivery(Base):
    """Newsletter delivery tracking."""

    __tablename__ = "newsletter_deliveries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    subject = Column(String(500), nullable=False)
    content_hash = Column(String(64), nullable=False)
    delivery_status = Column(String(50), default="pending", nullable=False)
    sent_at = Column(DateTime, nullable=True)
    opened_at = Column(DateTime, nullable=True)
    delivery_id = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)
    item_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="deliveries")

    # Constraints
    __table_args__ = (
        Index("idx_newsletter_deliveries_user_id", "user_id"),
        Index("idx_newsletter_deliveries_status", "delivery_status"),
        Index("idx_newsletter_deliveries_sent", "sent_at"),
    )


class UserInteraction(Base):
    """User interactions with content for personalization."""

    __tablename__ = "user_interactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    content_id = Column(UUID(as_uuid=True), ForeignKey("content_items.id"), nullable=False)
    interaction_type = Column(String(50), nullable=False)  # 'click', 'read', 'skip', 'like'
    interaction_value = Column(Float, nullable=True)  # reading time, engagement score
    item_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="interactions")
    content_item = relationship("ContentItem", back_populates="interactions")

    # Constraints
    __table_args__ = (
        Index("idx_user_interactions_user_id", "user_id"),
        Index("idx_user_interactions_content_id", "content_id"),
        Index("idx_user_interactions_type", "interaction_type"),
        Index("idx_user_interactions_created", "created_at"),
    )


class Database:
    """Database manager with async support."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = create_async_engine(
            database_url,
            echo=False,  # Set to True for SQL debugging
            pool_pre_ping=True,
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def init_tables(self) -> None:
        """Initialize database tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        """Close database connections."""
        await self.engine.dispose()

    def get_session(self) -> AsyncSession:
        """Get database session."""
        return self.session_factory()

    # User operations
    async def create_user(
        self,
        email: str,
        name: str,
        timezone: str = "UTC",
        github_username: Optional[str] = None,
    ) -> User:
        """Create a new user."""
        session = self.get_session()
        try:
            user = User(
                email=email,
                name=name,
                timezone=timezone,
                github_username=github_username,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user
        finally:
            await session.close()

    async def get_user_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        """Get user by ID with interests and recent interactions."""
        session = self.get_session()
        try:
            stmt = (
                select(User)
                .options(selectinload(User.interests))
                .where(User.id == user_id)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
        finally:
            await session.close()

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        session = self.get_session()
        try:
            stmt = select(User).where(User.email == email)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
        finally:
            await session.close()

    async def update_user_interests(
        self, user_id: uuid.UUID, interests: List[Dict[str, Any]]
    ) -> None:
        """Update user interests."""
        session = self.get_session()
        try:
            # Delete existing interests
            await session.execute(
                delete(UserInterest).where(UserInterest.user_id == user_id)
            )

            # Add new interests
            for interest_data in interests:
                interest = UserInterest(
                    user_id=user_id,
                    interest=interest_data["interest"],
                    weight=interest_data.get("weight", 1.0),
                )
                session.add(interest)

            await session.commit()
        finally:
            await session.close()

    # Content operations
    async def save_content_items(self, content_items: List[Dict[str, Any]]) -> None:
        """Save content items to database."""
        async with self.get_session() as session:
            for item_data in content_items:
                # Check if content already exists
                existing = await session.execute(
                    select(ContentItem).where(
                        ContentItem.content_hash == item_data["content_hash"]
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                content_item = ContentItem(**item_data)
                session.add(content_item)

            await session.commit()

    async def get_recent_content(
        self,
        hours: int = 24,
        limit: int = 100,
        sources: Optional[List[str]] = None,
    ) -> List[ContentItem]:
        """Get recent content items."""
        async with self.get_session() as session:
            stmt = (
                select(ContentItem)
                .where(
                    ContentItem.created_at
                    >= datetime.now(timezone.utc) - asyncio.get_event_loop().call_later(hours * 3600, lambda: None)
                )
                .order_by(ContentItem.relevance_score.desc())
                .limit(limit)
            )

            if sources:
                stmt = stmt.where(ContentItem.source.in_(sources))

            result = await session.execute(stmt)
            return result.scalars().all()

    # Delivery tracking
    async def create_delivery_record(
        self,
        user_id: uuid.UUID,
        subject: str,
        content_hash: str,
        delivery_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> NewsletterDelivery:
        """Create delivery record."""
        async with self.get_session() as session:
            delivery = NewsletterDelivery(
                user_id=user_id,
                subject=subject,
                content_hash=content_hash,
                delivery_id=delivery_id,
                metadata=metadata or {},
            )
            session.add(delivery)
            await session.commit()
            await session.refresh(delivery)
            return delivery

    async def update_delivery_status(
        self,
        delivery_id: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """Update delivery status."""
        async with self.get_session() as session:
            await session.execute(
                update(NewsletterDelivery)
                .where(NewsletterDelivery.delivery_id == delivery_id)
                .values(
                    delivery_status=status,
                    sent_at=datetime.now(timezone.utc) if status == "sent" else None,
                    error_message=error_message,
                )
            )
            await session.commit()

    # Analytics
    async def record_user_interaction(
        self,
        user_id: uuid.UUID,
        content_id: uuid.UUID,
        interaction_type: str,
        interaction_value: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record user interaction."""
        async with self.get_session() as session:
            interaction = UserInteraction(
                user_id=user_id,
                content_id=content_id,
                interaction_type=interaction_type,
                interaction_value=interaction_value,
                metadata=metadata or {},
            )
            session.add(interaction)
            await session.commit()

    async def get_user_interaction_stats(
        self, user_id: uuid.UUID, days: int = 30
    ) -> Dict[str, Any]:
        """Get user interaction statistics."""
        async with self.get_session() as session:
            since_date = datetime.now(timezone.utc) - asyncio.get_event_loop().call_later(days * 24 * 3600, lambda: None)

            # Get interaction counts by type
            stmt = (
                select(
                    UserInteraction.interaction_type,
                    func.count(UserInteraction.id).label("count"),
                )
                .where(
                    UserInteraction.user_id == user_id,
                    UserInteraction.created_at >= since_date,
                )
                .group_by(UserInteraction.interaction_type)
            )

            result = await session.execute(stmt)
            interaction_counts = dict(result.fetchall())

            return {
                "interaction_counts": interaction_counts,
                "total_interactions": sum(interaction_counts.values()),
            }


async def init_database(config: ApplicationConfig) -> Database:
    """Initialize database with configuration."""
    # Convert SQLite URL for async support
    database_url = config.database_url
    if database_url.startswith("sqlite:///"):
        database_url = database_url.replace("sqlite:///", "sqlite+aiosqlite:///")

    db = Database(database_url)
    await db.init_tables()
    return db


async def create_tables(db: AsyncSession = None) -> None:
    """Create all database tables."""
    # Use default database URL for setup
    from src.infrastructure.config import ApplicationConfig
    config = ApplicationConfig()
    database_url = config.database_url
    if database_url.startswith("sqlite:///"):
        database_url = database_url.replace("sqlite:///", "sqlite+aiosqlite:///")

    engine = create_async_engine(database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


async def get_database() -> AsyncIterator[AsyncSession]:
    """Get database session."""
    from src.infrastructure.config import ApplicationConfig
    config = ApplicationConfig()
    database_url = config.database_url
    if database_url.startswith("sqlite:///"):
        database_url = database_url.replace("sqlite:///", "sqlite+aiosqlite:///")

    engine = create_async_engine(database_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
            await engine.dispose()