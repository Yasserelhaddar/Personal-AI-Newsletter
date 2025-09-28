#!/usr/bin/env python3
"""Main entry point for Personal AI Newsletter Generator."""

import argparse
import asyncio
import sys
from pathlib import Path

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from src.infrastructure.logging import setup_logging, get_logger
from src.models.state import GenerationRequest
from src.workflows.newsletter import create_newsletter_workflow

logger = get_logger(__name__)


class NewsletterCLI:
    """Command-line interface for the newsletter generator."""

    def __init__(self):
        self.workflow_graph = None
        self.workflow = None

    def _ensure_workflow(self):
        """Lazy initialization of workflow."""
        if self.workflow is None:
            self.workflow_graph = create_newsletter_workflow()
            self.workflow = self.workflow_graph.compile()

    async def generate_newsletter(
        self,
        user_id: str,
        dry_run: bool = False,
        test_mode: bool = False
    ) -> bool:
        """Generate a newsletter for a specific user."""
        try:
            # Initialize workflow only when needed
            self._ensure_workflow()
            # Create generation request
            request = GenerationRequest(
                user_id=user_id,
                dry_run=dry_run,
                test_mode=test_mode
            )

            # Create initial state and run workflow
            from src.services.user_profile import UserProfileService
            from src.infrastructure.database import init_database
            from src.infrastructure.config import ApplicationConfig

            config = ApplicationConfig()
            db = await init_database(config)
            session = db.get_session()
            try:
                user_service = UserProfileService(session)
                user_profile = await user_service.get_user_profile(user_id)
            finally:
                await session.close()
                await db.close()

            if not user_profile:
                print(f"❌ User profile not found: {user_id}")
                return False

            # Create initial state
            from src.models.state import NewsletterGenerationState, GenerationMetadata
            initial_state = NewsletterGenerationState(
                user_profile=user_profile,
                generation_request=request,
                raw_content=[],
                analyzed_content=[],
                curated_newsletter=None,
                email_content=None,
                delivery_result=None,
                generation_metadata=GenerationMetadata(),
                errors=[],
                warnings=[],
                workflow_context={}
            )

            # Run workflow
            result = await self.workflow.ainvoke(initial_state)

            if result and result.get("delivery_result"):
                if result["delivery_result"].success:
                    print("✅ Newsletter generated and delivered successfully!")
                    if dry_run:
                        print("📝 This was a dry run - no actual email was sent")
                    return True
                else:
                    print(f"❌ Newsletter generation failed: {result['delivery_result'].error_message}")
                    return False
            else:
                print("❌ Newsletter generation failed")
                return False

        except Exception as e:
            logger.error(f"Newsletter generation failed: {e}")
            print(f"❌ Error: {e}")
            return False

    async def list_users(self) -> None:
        """List all configured users."""
        try:
            from src.services.user_profile import UserProfileService
            from src.infrastructure.database import init_database
            from src.infrastructure.config import ApplicationConfig

            config = ApplicationConfig()
            db = await init_database(config)

            session = db.get_session()
            try:
                service = UserProfileService(session)
                users = await service.list_users()

                if not users:
                    print("No users configured. Run setup first: uv run python -m src.main setup")
                    return

                print(f"\n📋 Configured Users ({len(users)}):")
                print("=" * 40)
                for user in users:
                    print(f"ID: {user.user_id}")
                    print(f"Name: {user.name}")
                    print(f"Email: {user.email}")
                    print(f"Topics: {', '.join(user.interests)}")
                    print(f"Max Articles: {user.max_articles}")
                    print("-" * 30)
            finally:
                await session.close()
                await db.close()

        except Exception as e:
            logger.error(f"Failed to list users: {e}")
            print(f"❌ Error listing users: {e}")

    async def test_config(self) -> bool:
        """Test the system configuration."""
        try:
            print("🧪 Testing system configuration...")

            # Test database
            from src.infrastructure.database import init_database
            from src.infrastructure.config import ApplicationConfig
            config = ApplicationConfig()
            db = await init_database(config)
            await db.close()
            print("  ✅ Database connection")

            # Test MCP configuration
            from src.infrastructure.config import load_mcp_config
            try:
                mcp_config = load_mcp_config()
                print(f"  ✅ MCP configuration ({len(mcp_config)} servers)")
            except Exception as e:
                print(f"  ⚠️  MCP configuration issue: {e}")

            # Test user profiles
            from src.services.user_profile import UserProfileService
            db2 = await init_database(config)
            session = db2.get_session()
            try:
                service = UserProfileService(session)
                users = await service.list_users()
                print(f"  ✅ User profiles ({len(users)} users)")
            finally:
                await session.close()
                await db2.close()

            print("\n✅ Configuration test completed!")
            return True

        except Exception as e:
            logger.error(f"Configuration test failed: {e}")
            print(f"❌ Configuration test failed: {e}")
            return False


def create_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Personal AI Newsletter Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python -m src.main generate --user john_doe
  uv run python -m src.main generate --user john_doe --dry-run
  uv run python -m src.main list-users
  uv run python -m src.main test-config
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Generate command
    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate and send a newsletter"
    )
    generate_parser.add_argument(
        "--user",
        required=True,
        help="User ID to generate newsletter for"
    )
    generate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate newsletter but don't send email"
    )
    generate_parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Use test data instead of real content collection"
    )

    # List users command
    subparsers.add_parser(
        "list-users",
        help="List all configured users"
    )

    # Test config command
    subparsers.add_parser(
        "test-config",
        help="Test system configuration"
    )

    # Setup command
    subparsers.add_parser(
        "setup",
        help="Run initial setup wizard"
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging"
    )

    return parser


async def main():
    """Main application entry point."""
    parser = create_parser()
    args = parser.parse_args()

    # Setup logging
    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logging(level=log_level)

    # Check if setup is needed
    config_path = Path("config/mcp_servers.json")
    if not config_path.exists() and args.command != "setup":
        print("⚠️  System not configured. Running setup first...")
        from src.setup import main as setup_main
        await setup_main()
        return

    try:
        if args.command == "generate":
            # Create CLI instance only when needed
            cli = NewsletterCLI()
            success = await cli.generate_newsletter(
                user_id=args.user,
                dry_run=args.dry_run,
                test_mode=args.test_mode
            )
            sys.exit(0 if success else 1)

        elif args.command == "list-users":
            # Create CLI instance only when needed
            cli = NewsletterCLI()
            await cli.list_users()

        elif args.command == "test-config":
            # Create CLI instance only when needed
            cli = NewsletterCLI()
            success = await cli.test_config()
            sys.exit(0 if success else 1)

        elif args.command == "setup":
            from src.setup import main as setup_main
            await setup_main()

        else:
            parser.print_help()
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\n❌ Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Application error: {e}")
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())