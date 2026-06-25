"""Management CLI for the Jira agile-delivery ingestion routine.

Commands are auto-discovered from :mod:`ingestion.cli.commands`, mirroring the
pattern used by the main Manager 360 app, so adding a new command is just a
matter of dropping a module that defines a ``click`` command into that package.
"""

import importlib
import pkgutil

import click


@click.group()
def cli():
    """Manager 360 - Jira agile-delivery ingestion."""
    pass


def discover_commands():
    """Auto-discover and register every command in the commands package."""
    package = importlib.import_module("ingestion.cli.commands")
    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"ingestion.cli.commands.{module_name}")
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, click.Command) and attr is not cli:
                cli.add_command(attr)


discover_commands()
