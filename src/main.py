#!/usr/bin/env python3
"""Main entry point for Personal AI Newsletter Generator."""

import argparse
import asyncio
import sys
import signal
from pathlib import Path
from datetime import datetime, timezone

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.live import Live
from rich import print as rprint

from src.infrastructure.logging import setup_logging, get_logger
from src.models.state import GenerationRequest
from src.workflows.newsletter import create_newsletter_workflow

console = Console()
logger = get_logger(__name__)


class NewsletterCLI:
    """Command-line interface for the newsletter generator."""

    def __init__(self):
        self.workflow_graph = None
        self.workflow = None
        self.running = False

    def _ensure_workflow(self):
        """Lazy initialization of workflow."""
        if self.workflow is None:
            with console.status("[bold blue]Initializing workflow..."):
                self.workflow_graph = create_newsletter_workflow()
                self.workflow = self.workflow_graph.compile()

    async def generate_newsletter_immediate(
        self,
        user_id: str,
        dry_run: bool = False,
        test_mode: bool = False
    ) -> bool:
        """Generate a newsletter immediately."""
        try:
            self._ensure_workflow()

            # Create generation request
            request = GenerationRequest(
                user_id=user_id,
                dry_run=dry_run,
                test_mode=test_mode
            )

            # Get user profile
            from src.services.user_profile import UserProfileService
            from src.infrastructure.database import init_database
            from src.infrastructure.config import ApplicationConfig

            config = ApplicationConfig()

            with console.status("[bold blue]Loading user profile..."):
                db = await init_database(config)
                session = db.get_session()
                try:
                    user_service = UserProfileService(session)
                    user_profile = await user_service.get_user_profile(user_id)
                finally:
                    await session.close()
                    await db.close()

            if not user_profile:
                console.print(f"[bold red]Error:[/bold red] User profile not found: {user_id}")
                return False

            # Check if using test email
            if config.is_using_test_email:
                console.print(Panel.fit(
                    "[yellow]Using Resend test email (onboarding@resend.dev)\n"
                    "For production use, configure a custom domain in .env[/yellow]",
                    title="Test Mode",
                    border_style="yellow"
                ))

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

            # Run workflow with progress
            with console.status("[bold green]Generating newsletter..."):
                result = await self.workflow.ainvoke(initial_state)

            if result and result.get("delivery_result"):
                if result["delivery_result"].success:
                    console.print("[bold green]Success:[/bold green] Newsletter generated and delivered successfully!")
                    if dry_run:
                        console.print("[dim]Note: This was a dry run - no actual email was sent[/dim]")
                    return True
                else:
                    console.print(f"[bold red]Error:[/bold red] Newsletter generation failed: {result['delivery_result'].error_message}")
                    return False
            else:
                console.print("[bold red]Error:[/bold red] Newsletter generation failed")
                return False

        except Exception as e:
            logger.error(f"Newsletter generation failed: {e}")
            console.print(f"[bold red]Error:[/bold red] {e}")
            return False

    async def run_scheduled_generation(self, user_id: str, dry_run: bool = False, test_mode: bool = False):
        """Run in scheduled mode - wait for the right time to send."""
        from src.models.user import should_send_newsletter
        from src.services.user_profile import UserProfileService
        from src.infrastructure.database import init_database
        from src.infrastructure.config import ApplicationConfig

        console.print(Panel.fit(
            f"[bold blue]Personal AI Newsletter Scheduler[/bold blue]\n"
            f"User: {user_id}\n"
            f"Mode: {'Dry Run' if dry_run else 'Live'}\n"
            f"Press Ctrl+C to stop",
            title="Scheduler Started",
            border_style="blue"
        ))

        self.running = True

        # Setup signal handlers
        def signal_handler(signum, frame):
            console.print("\n[yellow]Shutdown signal received. Stopping scheduler...[/yellow]")
            self.running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        config = ApplicationConfig()

        # Get user profile once
        db = await init_database(config)
        session = db.get_session()
        try:
            user_service = UserProfileService(session)
            user_profile = await user_service.get_user_profile(user_id)
        finally:
            await session.close()
            await db.close()

        if not user_profile:
            console.print(f"[bold red]Error:[/bold red] User profile not found: {user_id}")
            return False

        # Show schedule info
        schedule_info = Table(title="User Schedule Configuration")
        schedule_info.add_column("Setting", style="cyan")
        schedule_info.add_column("Value", style="white")
        schedule_info.add_row("Name", user_profile.name)
        schedule_info.add_row("Email", user_profile.email)
        schedule_info.add_row("Schedule Time", user_profile.schedule_time)
        schedule_info.add_row("Schedule Days", ', '.join([day.value.title() for day in user_profile.schedule_days]))
        schedule_info.add_row("Timezone", user_profile.timezone)

        console.print(schedule_info)
        console.print()

        last_check = None

        with Live(console=console, refresh_per_second=1) as live:
            while self.running:
                try:
                    current_time = datetime.now(timezone.utc)

                    # Update display every minute
                    if not last_check or (current_time - last_check).total_seconds() >= 60:
                        status_table = Table(title="Scheduler Status")
                        status_table.add_column("Item", style="cyan")
                        status_table.add_column("Value", style="white")
                        status_table.add_row("Current Time (UTC)", current_time.strftime('%Y-%m-%d %H:%M:%S'))
                        status_table.add_row("Next Check", "Checking every minute...")
                        status_table.add_row("Status", "[green]Running[/green]")

                        live.update(status_table)
                        last_check = current_time

                    # Check if it's time to send
                    if should_send_newsletter(user_profile, current_time):
                        live.update(Panel.fit(
                            "[bold green]Schedule matched! Generating newsletter...[/bold green]",
                            title="Sending Newsletter"
                        ))

                        success = await self.generate_newsletter_immediate(
                            user_id=user_id,
                            dry_run=dry_run,
                            test_mode=test_mode
                        )

                        if success:
                            # Update last sent time
                            db = await init_database(config)
                            session = db.get_session()
                            try:
                                await user_service.update_last_newsletter_sent(user_id, current_time)
                            finally:
                                await session.close()
                                await db.close()

                            console.print("[bold green]Newsletter sent successfully! Continuing to monitor...[/bold green]")
                        else:
                            console.print("[bold red]Failed to send newsletter. Continuing to monitor...[/bold red]")

                    # Wait before next check
                    await asyncio.sleep(60)  # Check every minute

                except Exception as e:
                    logger.error(f"Scheduler error: {e}")
                    console.print(f"[bold red]Scheduler error:[/bold red] {e}")
                    await asyncio.sleep(60)

        console.print("\n[yellow]Scheduler stopped.[/yellow]")
        return True

    async def list_users(self) -> None:
        """List all configured users."""
        try:
            from src.services.user_profile import UserProfileService
            from src.infrastructure.database import init_database
            from src.infrastructure.config import ApplicationConfig

            config = ApplicationConfig()

            with console.status("[bold blue]Loading users..."):
                db = await init_database(config)
                session = db.get_session()
                try:
                    service = UserProfileService(session)
                    users = await service.list_users()
                finally:
                    await session.close()
                    await db.close()

            if not users:
                console.print("[yellow]No users configured. Run setup first:[/yellow] [bold]uv run python -m src.main setup[/bold]")
                return

            users_table = Table(title=f"Configured Users ({len(users)})")
            users_table.add_column("ID", style="cyan", width=40)
            users_table.add_column("Name", style="white")
            users_table.add_column("Email", style="blue")
            users_table.add_column("Topics", style="green")
            users_table.add_column("Schedule", style="yellow")

            for user in users:
                schedule_info = f"{user.schedule_time} on {', '.join([day.value[:3].title() for day in user.schedule_days])}"
                users_table.add_row(
                    str(user.user_id),  # Show full ID
                    user.name,
                    user.email,
                    ', '.join(user.interests[:3]) + ("..." if len(user.interests) > 3 else ""),
                    schedule_info
                )

            console.print(users_table)

        except Exception as e:
            logger.error(f"Failed to list users: {e}")
            console.print(f"[bold red]Error listing users:[/bold red] {e}")

    async def test_config(self) -> bool:
        """Test the system configuration."""
        try:
            console.print(Panel.fit(
                "[bold blue]Testing system configuration...[/bold blue]",
                title="Configuration Test"
            ))

            # Test database
            from src.infrastructure.database import init_database
            from src.infrastructure.config import ApplicationConfig

            config = ApplicationConfig()
            db = await init_database(config)
            await db.close()
            console.print("[green]✓[/green] Database connection")

            # Test MCP configuration
            from src.infrastructure.config import load_mcp_config
            try:
                mcp_config = load_mcp_config()
                console.print(f"[green]✓[/green] MCP configuration ({len(mcp_config)} servers)")
            except Exception as e:
                console.print(f"[yellow]![/yellow] MCP configuration issue: {e}")

            # Test user profiles
            from src.services.user_profile import UserProfileService
            db2 = await init_database(config)
            session = db2.get_session()
            try:
                service = UserProfileService(session)
                users = await service.list_users()
                console.print(f"[green]✓[/green] User profiles ({len(users)} users)")
            finally:
                await session.close()
                await db2.close()

            console.print("\n[bold green]Configuration test completed successfully![/bold green]")
            return True

        except Exception as e:
            logger.error(f"Configuration test failed: {e}")
            console.print(f"[bold red]Configuration test failed:[/bold red] {e}")
            return False


def create_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Personal AI Newsletter Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python -m src.main generate --user john_doe --immediate
  uv run python -m src.main generate --user john_doe
  uv run python -m src.main list-users
  uv run python -m src.main setup
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Generate command
    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate newsletter (scheduled or immediate)"
    )
    generate_parser.add_argument(
        "--user",
        required=True,
        help="User ID to generate newsletter for"
    )
    generate_parser.add_argument(
        "--immediate",
        action="store_true",
        help="Generate newsletter immediately (ignore schedule)"
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
        console.print(Panel.fit(
            "[yellow]System not configured. Please run setup first:[/yellow]\n"
            "[bold]uv run python -m src.main setup[/bold]",
            title="Setup Required",
            border_style="yellow"
        ))
        return

    try:
        if args.command == "generate":
            cli = NewsletterCLI()

            if args.immediate:
                # Immediate generation
                success = await cli.generate_newsletter_immediate(
                    user_id=args.user,
                    dry_run=args.dry_run,
                    test_mode=args.test_mode
                )
                sys.exit(0 if success else 1)
            else:
                # Scheduled generation - run continuously
                await cli.run_scheduled_generation(
                    user_id=args.user,
                    dry_run=args.dry_run,
                    test_mode=args.test_mode
                )

        elif args.command == "list-users":
            cli = NewsletterCLI()
            await cli.list_users()

        elif args.command == "setup":
            from src.setup import main as setup_main
            await setup_main()

        else:
            parser.print_help()
            sys.exit(1)

    except KeyboardInterrupt:
        console.print("\n\n[yellow]Operation cancelled by user[/yellow]")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Application error: {e}")
        console.print(f"[bold red]Unexpected error:[/bold red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())