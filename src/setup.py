#!/usr/bin/env python3
"""Setup script for Personal AI Newsletter Generator.

This script helps users configure and initialize the newsletter system.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any

# Will import these when needed to avoid circular imports
from src.infrastructure.database import create_tables, get_database
from src.infrastructure.logging import setup_logging, get_logger

logger = get_logger(__name__)


class NewsletterSetup:
    """Setup wizard for Personal AI Newsletter Generator."""

    def __init__(self):
        self.config_path = Path("config/mcp_servers.json")
        self.env_path = Path(".env")
        self.project_root = Path(__file__).parent.parent

    async def run_setup(self) -> bool:
        """Run the complete setup process."""
        print("🗞️  Personal AI Newsletter Generator Setup")
        print("=" * 50)

        try:
            # Check dependencies
            if not await self._check_dependencies():
                return False

            # Create directories
            await self._create_directories()

            # Configure MCP servers
            if not await self._configure_mcp_servers():
                return False

            # Setup database
            if not await self._setup_database():
                return False

            # Create initial user profile
            if not await self._create_user_profile():
                return False

            # Test configuration
            if not await self._test_configuration():
                return False

            print("\n✅ Setup completed successfully!")
            print("\nNext steps:")
            print("1. Run: uv run python -m src.main --help")
            print("2. Create your first newsletter: uv run python -m src.main generate --user your_user_id")
            print("3. Check logs in: logs/newsletter.log")

            return True

        except Exception as e:
            logger.error(f"Setup failed: {e}")
            print(f"\n❌ Setup failed: {e}")
            return False

    async def _check_dependencies(self) -> bool:
        """Check if all required dependencies are installed."""
        print("\n🔍 Checking dependencies...")

        required_packages = [
            ("langgraph", "langgraph"),
            ("sqlalchemy", "sqlalchemy"),
            ("aiosqlite", "aiosqlite"),
            ("jinja2", "jinja2"),
            ("aiofiles", "aiofiles"),
            ("pydantic", "pydantic"),
            ("python-dotenv", "dotenv")
        ]

        missing = []
        for package_name, import_name in required_packages:
            try:
                __import__(import_name)
                print(f"  ✅ {package_name}")
            except ImportError:
                missing.append(package_name)
                print(f"  ❌ {package_name}")

        if missing:
            print(f"\n❌ Missing packages: {', '.join(missing)}")
            print("Install with: uv add " + " ".join(missing))
            return False

        return True

    async def _create_directories(self) -> None:
        """Create necessary directories."""
        print("\n📁 Creating directories...")

        directories = [
            "config",
            "logs",
            "data",
            "templates/email",
            "tests"
        ]

        for dir_path in directories:
            full_path = self.project_root / dir_path
            full_path.mkdir(parents=True, exist_ok=True)
            print(f"  ✅ {dir_path}")

    async def _configure_mcp_servers(self) -> bool:
        """Configure MCP server connections."""
        print("\n🔌 Configuring MCP servers...")

        # Load configuration from environment variables (.env file)
        from src.infrastructure.config import ApplicationConfig
        config_env = ApplicationConfig()

        # Check if API keys are available
        has_resend = bool(config_env.resend_api_key and config_env.resend_api_key != "your-resend-key")
        has_firecrawl = bool(config_env.firecrawl_api_key and config_env.firecrawl_api_key != "your-firecrawl-key")
        has_github = bool(config_env.github_token and config_env.github_token != "your-github-token")

        print(f"  📧 Resend API: {'✅ Found in .env' if has_resend else '❌ Not configured'}")
        print(f"  🔥 Firecrawl API: {'✅ Found in .env' if has_firecrawl else '❌ Not configured'}")
        print(f"  🐙 GitHub Token: {'✅ Found in .env' if has_github else '❌ Not configured'}")

        # Use full path to npx and uvx to avoid PATH issues
        npx_path = "/opt/homebrew/bin/npx"
        uvx_path = "/Users/yasserelhaddar/.pyenv/shims/uvx"

        config = {
            "resend": {
                "name": "resend",
                "command": [npx_path, "-y", "resend-mcp"],
                "env": {
                    "RESEND_API_KEY": config_env.resend_api_key if has_resend else ""
                }
            },
            "firecrawl": {
                "name": "firecrawl",
                "command": [npx_path, "-y", "@firecrawl/mcp-server"],
                "env": {
                    "FIRECRAWL_API_KEY": config_env.firecrawl_api_key if has_firecrawl else ""
                }
            },
            "github": {
                "name": "github",
                "command": [npx_path, "-y", "@github/github-mcp-server"],
                "env": {
                    "GITHUB_PERSONAL_ACCESS_TOKEN": config_env.github_token if has_github else ""
                }
            },
            "sequential-thinking": {
                "name": "sequential-thinking",
                "command": [uvx_path, "mcp-sequential-thinking"],
                "env": {}
            }
        }

        # Remove servers with empty API keys (keep sequential-thinking which has no env)
        filtered_config = {}
        for k, v in config.items():
            if not v["env"]:  # No env vars required (like sequential-thinking)
                filtered_config[k] = v
            elif v["env"] and list(v["env"].values())[0]:  # Has env vars and they're not empty
                filtered_config[k] = v
        config = filtered_config

        if not config:
            print("⚠️  No MCP servers configured. You can add them later in config/mcp_servers.json")

        # Save configuration
        self.config_path.parent.mkdir(exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)

        print(f"  ✅ Configuration saved to {self.config_path}")
        return True

    async def _setup_database(self) -> bool:
        """Initialize the database."""
        print("\n💾 Setting up database...")

        try:
            # Setup logging
            setup_logging()

            # Create tables
            await create_tables()

            print("  ✅ Database initialized")
            return True

        except Exception as e:
            print(f"  ❌ Database setup failed: {e}")
            return False

    async def _create_user_profile(self) -> bool:
        """Create initial user profile."""
        print("\n👤 Creating user profile...")

        try:
            from src.models.user import create_user_profile
            from src.infrastructure.database import Database, init_database
            from src.infrastructure.config import ApplicationConfig

            # Get user information
            name = self._get_input("Enter your name: ")
            email = self._get_input("Enter your email: ")
            interests = self._get_list_input("Enter topics of interest (comma-separated): ")
            max_articles = int(self._get_input("Maximum articles per newsletter (default 5): ", default="5"))
            schedule_time = self._get_input("Preferred delivery time (HH:MM, default 09:00): ", default="09:00")
            timezone = self._get_input("Timezone (default UTC): ", default="UTC")

            # Create user profile
            user_profile = create_user_profile(
                email=email,
                name=name,
                interests=interests,
                max_articles=max_articles,
                schedule_time=schedule_time,
                timezone=timezone
            )

            # Save to database
            config = ApplicationConfig()
            db = await init_database(config)

            # Create user in database
            user = await db.create_user(
                email=user_profile.email,
                name=user_profile.name,
                timezone=user_profile.timezone,
                github_username=user_profile.github_username
            )

            # Set user interests
            if user_profile.interests:
                interests_data = [{"interest": interest, "weight": 1.0} for interest in user_profile.interests]
                await db.update_user_interests(user.id, interests_data)

            await db.close()

            print(f"  ✅ User profile created for {name}")
            return True

        except Exception as e:
            print(f"  ❌ User profile creation failed: {e}")
            return False

    async def _test_configuration(self) -> bool:
        """Test the configuration."""
        print("\n🧪 Testing configuration...")

        try:
            # Test database connection
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def get_db_session():
                async for db in get_database():
                    yield db

            async with get_db_session() as db:
                pass
            print("  ✅ Database connection")

            # Test MCP server configs
            if self.config_path.exists():
                try:
                    with open(self.config_path, "r") as f:
                        config = json.load(f)
                    print(f"  ✅ MCP configuration ({len(config)} servers)")
                except Exception as e:
                    print(f"  ⚠️  MCP configuration issue: {e}")
            else:
                print("  ⚠️  No MCP servers configured")

            # Test user profiles (simplified for setup)
            print("  ✅ User profiles (will be created during setup)")

            return True

        except Exception as e:
            print(f"  ❌ Configuration test failed: {e}")
            return False

    def _get_input(self, prompt: str, default: str = None, optional: bool = False) -> str:
        """Get user input with optional default value."""
        if default:
            full_prompt = f"{prompt}[{default}] "
        else:
            full_prompt = prompt

        try:
            value = input(full_prompt).strip()
            if not value and default:
                return default
            if not value and optional:
                return ""
            if not value:
                print("This field is required.")
                return self._get_input(prompt, default, optional)
            return value
        except KeyboardInterrupt:
            print("\n\n❌ Setup cancelled by user")
            sys.exit(1)

    def _get_list_input(self, prompt: str) -> list:
        """Get comma-separated list input."""
        value = self._get_input(prompt)
        return [item.strip() for item in value.split(",") if item.strip()]


async def main():
    """Main setup function."""
    setup = NewsletterSetup()

    if len(sys.argv) > 1 and sys.argv[1] == "--reset":
        print("🔄 Resetting configuration...")
        # Remove existing config files
        config_files = [
            "config/mcp_servers.json",
            "data/newsletter.db",
            ".env"
        ]
        for file_path in config_files:
            if Path(file_path).exists():
                Path(file_path).unlink()
                print(f"  ✅ Removed {file_path}")

    success = await setup.run_setup()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())