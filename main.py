import argparse
import asyncio
from pathlib import Path

import discord
import genshin
import prometheus_client
import sentry_sdk
from discord.ext import commands

import database
from utility import LOG, config, sentry_logging

intents = discord.Intents.default()
argparser = argparse.ArgumentParser()


class GenshinDiscordBot(commands.AutoShardedBot):
    def __init__(self):
        self.db = database.Database
        super().__init__(
            command_prefix=commands.when_mentioned_or("$"),
            intents=intents,
            application_id=config.application_id,
            allowed_contexts=discord.app_commands.AppCommandContext(
                guild=True, dm_channel=True, private_channel=True
            ),
            allowed_installs=discord.app_commands.AppInstallationType(guild=True, user=True),
        )

    async def setup_hook(self) -> None:
        # Load jishaku
        await self.load_extension("jishaku")

        # Initialize the database
        await database.Database.init()

        # Initialize Genshin API character names
        await genshin.utility.update_characters_enka(["en-us"])

        # Load all cogs from the 'cogs' folder
        for filepath in Path("./cogs").glob("**/*cog.py"):
            parts = list(filepath.parts)
            parts[-1] = filepath.stem
            await self.load_extension(".".join(parts))

        # Load all cogs from the 'cogs_external' folder
        for filepath in Path("./cogs_external").glob("**/*.py"):
            cog_name = Path(filepath).stem
            await self.load_extension(f"cogs_external.{cog_name}")

        # Sync slash commands
        if config.test_server_id is not None:
            test_guild = discord.Object(id=config.test_server_id)
            self.tree.copy_global_to(guild=test_guild)
            await self.tree.sync(guild=test_guild)
        await self.tree.sync()

        # Start Prometheus Server
        if config.prometheus_server_port is not None:
            prometheus_client.start_http_server(config.prometheus_server_port)
            LOG.System(f"prometheus server: started on port {config.prometheus_server_port}")

    async def on_ready(self):
        LOG.System(f"on_ready: You have logged in as {self.user}")
        LOG.System(f"on_ready: Total {len(self.guilds)} servers connected")

    async def close(self) -> None:
        # Close the database
        await database.Database.close()
        LOG.System("on_close: The database is closed")
        await super().close()
        LOG.System("on_close: Bot has stopped")

    async def on_command(self, ctx: commands.Context):
        LOG.CmdResult(ctx)

    async def on_command_error(self, ctx: commands.Context, error):
        LOG.ErrorLog(ctx, error)


argparser.add_argument("--migrate_database", action="store_true")
args = argparser.parse_args()

if args.migrate_database:
    asyncio.run(database.migration.migrate())
    exit()

sentry_sdk.init(dsn=config.sentry_sdk_dsn, integrations=[sentry_logging], traces_sample_rate=1.0)

client = GenshinDiscordBot()


@client.tree.error
async def on_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
) -> None:
    LOG.ErrorLog(interaction, error)
    sentry_sdk.capture_exception(error)


client.run(config.bot_token)
