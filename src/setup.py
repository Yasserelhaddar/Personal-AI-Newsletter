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

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, IntPrompt
from rich import print as rprint

# Will import these when needed to avoid circular imports
from src.infrastructure.database import create_tables, get_database
from src.infrastructure.logging import setup_logging, get_logger

console = Console()
logger = get_logger(__name__)


class NewsletterSetup:
    """Setup wizard for Personal AI Newsletter Generator."""

    def __init__(self):
        self.config_path = Path("config/mcp_servers.json")
        self.env_path = Path(".env")
        self.project_root = Path(__file__).parent.parent

    async def run_setup(self) -> bool:
        """Run the complete setup process."""
        console.print(Panel.fit(
            "[bold blue]Personal AI Newsletter Generator Setup[/bold blue]",
            title="Setup Wizard",
            border_style="blue"
        ))

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

            console.print("\n[bold green]Setup completed successfully![/bold green]")
            console.print(Panel.fit(
                "[bold]Next steps:[/bold]\n"
                "1. Run: [cyan]uv run python -m src.main --help[/cyan]\n"
                "2. Create your first newsletter: [cyan]uv run python -m src.main generate --user your_user_id[/cyan]\n"
                "3. Check logs in: [cyan]logs/newsletter.log[/cyan]",
                title="What's Next",
                border_style="green"
            ))

            return True

        except Exception as e:
            logger.error(f"Setup failed: {e}")
            console.print(f"\n[bold red]Setup failed:[/bold red] {e}")
            return False

    async def _check_dependencies(self) -> bool:
        """Check if all required dependencies are installed."""
        with console.status("[bold blue]Checking dependencies..."):
            pass

        required_packages = [
            ("langgraph", "langgraph"),
            ("sqlalchemy", "sqlalchemy"),
            ("aiosqlite", "aiosqlite"),
            ("jinja2", "jinja2"),
            ("aiofiles", "aiofiles"),
            ("pydantic", "pydantic"),
            ("python-dotenv", "dotenv")
        ]

        deps_table = Table(title="Dependencies")
        deps_table.add_column("Package", style="cyan")
        deps_table.add_column("Status", style="white")

        missing = []
        for package_name, import_name in required_packages:
            try:
                __import__(import_name)
                deps_table.add_row(package_name, "[green]Found[/green]")
            except ImportError:
                missing.append(package_name)
                deps_table.add_row(package_name, "[red]Missing[/red]")

        console.print(deps_table)

        if missing:
            console.print(f"\n[bold red]Missing packages:[/bold red] {', '.join(missing)}")
            console.print(f"[dim]Install with:[/dim] [cyan]uv add {' '.join(missing)}[/cyan]")
            return False

        return True

    async def _create_directories(self) -> None:
        """Create necessary directories."""
        directories = [
            "config",
            "logs",
            "data",
            "templates/email",
            "tests"
        ]

        with console.status("[bold blue]Creating directories..."):
            for dir_path in directories:
                full_path = self.project_root / dir_path
                full_path.mkdir(parents=True, exist_ok=True)

        dir_table = Table(title="Created Directories")
        dir_table.add_column("Directory", style="cyan")
        dir_table.add_column("Status", style="green")

        for dir_path in directories:
            dir_table.add_row(dir_path, "Created")

        console.print(dir_table)

    async def _configure_mcp_servers(self) -> bool:
        """Configure MCP server connections."""
        with console.status("[bold blue]Configuring MCP servers..."):
            pass

        # Load configuration from environment variables (.env file)
        from src.infrastructure.config import ApplicationConfig
        config_env = ApplicationConfig()

        # Check if API keys are available
        has_resend = bool(config_env.resend_api_key and config_env.resend_api_key != "your-resend-key")
        has_firecrawl = bool(config_env.firecrawl_api_key and config_env.firecrawl_api_key != "your-firecrawl-key")
        has_github = bool(config_env.github_token and config_env.github_token != "your-github-token")

        # Check domain configuration
        has_domain = bool(config_env.domain and config_env.domain != "" and config_env.domain != "yourdomain.com")

        config_table = Table(title="MCP Server Configuration")
        config_table.add_column("Service", style="cyan")
        config_table.add_column("Status", style="white")

        config_table.add_row("Resend API", "[green]Found in .env[/green]" if has_resend else "[red]Not configured[/red]")
        config_table.add_row("Firecrawl API", "[green]Found in .env[/green]" if has_firecrawl else "[red]Not configured[/red]")
        config_table.add_row("GitHub Token", "[green]Found in .env[/green]" if has_github else "[red]Not configured[/red]")

        if not has_domain:
            config_table.add_row("Domain", "[yellow]Not configured (will use test email: onboarding@resend.dev)[/yellow]")
        else:
            config_table.add_row("Domain", f"[green]{config_env.domain} (newsletter@{config_env.domain})[/green]")

        console.print(config_table)

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
            console.print("[yellow]No MCP servers configured. You can add them later in config/mcp_servers.json[/yellow]")

        # Save configuration
        self.config_path.parent.mkdir(exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)

        console.print(f"[green]Configuration saved to {self.config_path}[/green]")
        return True

    async def _setup_database(self) -> bool:
        """Initialize the database."""
        try:
            with console.status("[bold blue]Setting up database..."):
                # Setup logging
                setup_logging()
                # Create tables
                await create_tables()

            console.print("[green]Database initialized[/green]")
            return True

        except Exception as e:
            console.print(f"[bold red]Database setup failed:[/bold red] {e}")
            return False

    async def _create_user_profile(self) -> bool:
        """Create initial user profile."""
        console.print("\n[bold blue]Creating user profile...[/bold blue]")

        try:
            from src.models.user import create_user_profile
            from src.infrastructure.database import Database, init_database
            from src.infrastructure.config import ApplicationConfig

            # Get user information
            name = Prompt.ask("Enter your name")
            email = Prompt.ask("Enter your email")
            interests_input = Prompt.ask("Enter topics of interest (comma-separated)")
            interests = [item.strip() for item in interests_input.split(",") if item.strip()]
            max_articles = IntPrompt.ask("Maximum articles per newsletter", default=5)
            schedule_time = Prompt.ask("Preferred delivery time (HH:MM)", default="09:00")
            timezone = Prompt.ask("Timezone", default="UTC")

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

            console.print(f"[green]User profile created for {name}[/green]")
            return True

        except Exception as e:
            console.print(f"[bold red]User profile creation failed:[/bold red] {e}")
            return False

    async def _test_configuration(self) -> bool:
        """Test the configuration."""
        with console.status("[bold blue]Testing configuration..."):
            pass

        try:
            # Test database connection
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def get_db_session():
                async for db in get_database():
                    yield db

            async with get_db_session() as db:
                pass

            # Test MCP server configs
            mcp_status = "Not configured"
            if self.config_path.exists():
                try:
                    with open(self.config_path, "r") as f:
                        config = json.load(f)
                    mcp_status = f"{len(config)} servers"
                except Exception as e:
                    mcp_status = f"Configuration issue: {e}"

            test_table = Table(title="Configuration Test Results")
            test_table.add_column("Component", style="cyan")
            test_table.add_column("Status", style="white")

            test_table.add_row("Database connection", "[green]Success[/green]")
            test_table.add_row("MCP configuration", f"[green]{mcp_status}[/green]" if "servers" in mcp_status else f"[yellow]{mcp_status}[/yellow]")
            test_table.add_row("User profiles", "[green]Ready[/green]")

            console.print(test_table)
            return True

        except Exception as e:
            console.print(f"[bold red]Configuration test failed:[/bold red] {e}")
            return False



async def main():
    """Main setup function."""
    setup = NewsletterSetup()

    if len(sys.argv) > 1 and sys.argv[1] == "--reset":
        console.print("[bold yellow]Resetting configuration...[/bold yellow]")
        # Remove existing config files
        config_files = [
            "config/mcp_servers.json",
            "data/newsletter.db",
            ".env"
        ]
        for file_path in config_files:
            if Path(file_path).exists():
                Path(file_path).unlink()
                console.print(f"[green]Removed {file_path}[/green]")

    success = await setup.run_setup()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())