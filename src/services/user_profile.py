"""User profile service for the Personal AI Newsletter Generator."""

from datetime import datetime
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select

from src.infrastructure.database import User, UserInterest
from src.models.user import UserProfile, create_user_profile


class UserProfileService:
    """Service for managing user profiles."""

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    async def list_users(self) -> List[UserProfile]:
        """List all users."""
        try:
            # Get all users with their interests
            stmt = select(User)
            result = await self.db_session.execute(stmt)
            db_users = result.scalars().all()

            users = []
            for db_user in db_users:
                # Get user interests
                interests_stmt = select(UserInterest).where(UserInterest.user_id == db_user.id)
                interests_result = await self.db_session.execute(interests_stmt)
                interests = interests_result.scalars().all()

                # Convert to UserProfile
                user_profile = UserProfile(
                    user_id=str(db_user.id),
                    email=db_user.email,
                    name=db_user.name,
                    timezone=db_user.timezone,
                    github_username=db_user.github_username,
                    interests=[interest.interest for interest in interests],
                    created_at=db_user.created_at,
                    updated_at=db_user.updated_at
                )
                users.append(user_profile)

            return users

        except Exception as e:
            raise Exception(f"Failed to list users: {e}")

    async def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        """Get a user profile by ID."""
        try:
            # For simplicity, treat user_id as email if it contains @
            if "@" in user_id:
                stmt = select(User).where(User.email == user_id)
            else:
                # Try to find by ID (convert to UUID if needed)
                import uuid
                try:
                    uuid_id = uuid.UUID(user_id)
                    stmt = select(User).where(User.id == uuid_id)
                except ValueError:
                    # If not a valid UUID, try by email
                    stmt = select(User).where(User.email == user_id)

            result = await self.db_session.execute(stmt)
            db_user = result.scalar_one_or_none()

            if not db_user:
                return None

            # Get user interests
            interests_stmt = select(UserInterest).where(UserInterest.user_id == db_user.id)
            interests_result = await self.db_session.execute(interests_stmt)
            interests = interests_result.scalars().all()

            # Convert to UserProfile
            user_profile = UserProfile(
                user_id=str(db_user.id),
                email=db_user.email,
                name=db_user.name,
                timezone=db_user.timezone,
                github_username=db_user.github_username,
                interests=[interest.interest for interest in interests],
                created_at=db_user.created_at,
                updated_at=db_user.updated_at
            )

            return user_profile

        except Exception as e:
            raise Exception(f"Failed to get user profile: {e}")

    async def update_last_newsletter_sent(self, user_id: str, sent_time: datetime) -> None:
        """Update the last newsletter sent timestamp for a user."""
        try:
            # Find the user
            if "@" in user_id:
                stmt = select(User).where(User.email == user_id)
            else:
                import uuid
                try:
                    uuid_id = uuid.UUID(user_id)
                    stmt = select(User).where(User.id == uuid_id)
                except ValueError:
                    stmt = select(User).where(User.email == user_id)

            result = await self.db_session.execute(stmt)
            db_user = result.scalar_one_or_none()

            if not db_user:
                raise Exception(f"User not found: {user_id}")

            # Update the last newsletter sent time
            db_user.updated_at = sent_time
            await self.db_session.commit()

        except Exception as e:
            await self.db_session.rollback()
            raise Exception(f"Failed to update last newsletter sent: {e}")