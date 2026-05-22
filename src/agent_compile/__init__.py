"""agent-compile — manage agent templates and compile agent instances."""

# Single source of truth for the version — bump this one line at a milestone.
# pyproject.toml reads it via [tool.setuptools.dynamic]; `agent-compile
# --version` appends the git short-rev for editable checkouts (see
# __main__._display_version), so every install is traceable between bumps.
__version__ = "0.3.0"
