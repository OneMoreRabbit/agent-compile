"""agent-compile CLI entry.

Pass 1 ships ``template list`` and the top-level ``list`` verb against the
scaffolding modules. Remaining verbs land in later passes.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.tree import Tree

from . import __version__
from . import bless as bless_mod
from . import compile as compile_mod
from . import config as config_mod
from . import diff as diff_mod
from . import exit_codes
from . import identifiers
from . import matrix as matrix_mod
from . import registry as registry_mod
from . import resolver as resolver_mod
from . import template_ops as template_ops_mod
from . import test_runner as test_runner_mod
from . import verify as verify_mod

console = Console()
err = Console(stderr=True)


def _load_config(
    registry_root: Optional[str], org_routing: Optional[str]
) -> config_mod.Config:
    override = Path(registry_root).expanduser() if registry_root else None
    routing_override = Path(org_routing).expanduser() if org_routing else None
    try:
        return config_mod.load(
            registry_root_override=override,
            org_routing_path_override=routing_override,
        )
    except (FileNotFoundError, ValueError) as e:
        err.print(f"[red]configuration error:[/red] {e}")
        sys.exit(exit_codes.CONFIG)


@click.group(help="agent-compile — manage agent templates and compile agent instances.")
@click.option("--registry-root", type=click.Path(), default=None, help="Override the registry root path.")
@click.option(
    "--org-routing",
    type=click.Path(),
    default=None,
    help="Override the org_routing.yml path (default: ../inventory/group_vars/all/org_routing.yml relative to the registry root).",
)
@click.option("--json", "json_output", is_flag=True, help="Machine-readable output.")
@click.option("-v", "--verbose", is_flag=True, help="Log subprocess invocations.")
@click.option("-q", "--quiet", is_flag=True, help="Errors only.")
@click.version_option(version=__version__)
@click.pass_context
def cli(
    ctx: click.Context,
    registry_root: Optional[str],
    org_routing: Optional[str],
    json_output: bool,
    verbose: bool,
    quiet: bool,
) -> None:
    ctx.ensure_object(dict)
    ctx.obj["config"] = _load_config(registry_root, org_routing)
    ctx.obj["json"] = json_output
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet


@cli.group(help="Template management subcommands.")
def template() -> None:
    pass


@template.command("list", help="Tree view of templates.")
@click.argument("flavour", required=False)
@click.pass_context
def template_list_cmd(ctx: click.Context, flavour: Optional[str]) -> None:
    cfg: config_mod.Config = ctx.obj["config"]
    try:
        data = registry_mod.list_templates(cfg, flavour=flavour)
    except registry_mod.RegistryError as e:
        err.print(f"[red]error:[/red] {e}")
        sys.exit(exit_codes.NOT_FOUND)
    if not data:
        console.print("[yellow](no templates found)[/yellow]")
        return
    root = Tree("templates")
    for flav, names in data.items():
        flav_node = root.add(f"[bold]{flav}[/bold]")
        for name, versions in names.items():
            name_node = flav_node.add(name)
            for v in versions:
                name_node.add(f"v{v}")
    console.print(root)


@cli.command("list", help="List agents in the registry.")
@click.pass_context
def agents_list_cmd(ctx: click.Context) -> None:
    cfg: config_mod.Config = ctx.obj["config"]
    try:
        reg = registry_mod.load_agent_registry(cfg)
    except registry_mod.RegistryError as e:
        err.print(f"[red]error:[/red] {e}")
        sys.exit(exit_codes.NOT_FOUND)
    agents = reg.get("agents") or []
    if not agents:
        console.print("[yellow](no agents in registry)[/yellow]")
        return
    for a in agents:
        # template/image live under the `app` block in the v0.4 schema.
        # Agents without an `app` block (not compilable by agent-compile)
        # show "—".
        app = a.get("app") or {}
        template = app.get("template") or "—"
        image = app.get("image") or "—"
        console.print(f"  {a.get('name')} — template={template} image={image}")


def _not_implemented(verb: str) -> None:
    err.print(f"[yellow]not implemented yet:[/yellow] {verb} (pending later pass)")
    sys.exit(exit_codes.CONFIG)


@template.command("new", help="Create v1 of a new template from an image_defaults bundle.")
@click.argument("template_handle")
@click.option("--from-image", "from_image", required=True, help="<flavour>:<image_version>")
@click.option("--description", default="", help="Free-form description for the template.")
@click.pass_context
def template_new_cmd(
    ctx: click.Context, template_handle: str, from_image: str, description: str
) -> None:
    cfg: config_mod.Config = ctx.obj["config"]
    try:
        flavour, name = identifiers.parse_template_handle(template_handle)
        image_ref = identifiers.parse_image_ref(from_image)
    except identifiers.IdentifierError as e:
        err.print(f"[red]error:[/red] {e}")
        sys.exit(exit_codes.TEMPLATE_SCHEMA)

    new_id = identifiers.TemplateID(flavour=flavour, name=name, version=1)
    image_defaults_ref = identifiers.ImageDefaultsRef(
        flavour=image_ref.flavour, image_version=image_ref.image_version
    )
    try:
        path = template_ops_mod.new_template(
            cfg, new_id, image_defaults_ref, description=description
        )
    except template_ops_mod.TemplateOpsError as e:
        msg = str(e)
        if "already exists" in msg:
            err.print(f"[red]error:[/red] {msg}")
            sys.exit(exit_codes.TEMPLATE_EXISTS)
        if "flavour" in msg:
            err.print(f"[red]error:[/red] {msg}")
            sys.exit(exit_codes.FLAVOUR_MISMATCH)
        err.print(f"[red]error:[/red] {msg}")
        sys.exit(exit_codes.NOT_FOUND)
    console.print(f"[green]created[/green] {new_id} at {path}")


@template.command("fork", help="Copy an existing template's overrides into a new template name.")
@click.argument("source_id")
@click.option("--as", "new_handle", required=True, help="<flavour>:<new_name>")
@click.option("--description", default="", help="Free-form description.")
@click.pass_context
def template_fork_cmd(
    ctx: click.Context, source_id: str, new_handle: str, description: str
) -> None:
    cfg: config_mod.Config = ctx.obj["config"]
    try:
        src = identifiers.parse_template_id(source_id)
        flavour, name = identifiers.parse_template_handle(new_handle)
    except identifiers.IdentifierError as e:
        err.print(f"[red]error:[/red] {e}")
        sys.exit(exit_codes.TEMPLATE_SCHEMA)

    new_id = identifiers.TemplateID(flavour=flavour, name=name, version=1)
    try:
        path = template_ops_mod.fork_template(cfg, src, new_id, description=description)
    except registry_mod.RegistryError as e:
        err.print(f"[red]error:[/red] {e}")
        sys.exit(exit_codes.NOT_FOUND)
    except template_ops_mod.TemplateOpsError as e:
        msg = str(e)
        if "already exists" in msg:
            err.print(f"[red]error:[/red] {msg}")
            sys.exit(exit_codes.TEMPLATE_EXISTS)
        if "flavour" in msg or "cross-flavour" in msg:
            err.print(f"[red]error:[/red] {msg}")
            sys.exit(exit_codes.FLAVOUR_MISMATCH)
        err.print(f"[red]error:[/red] {msg}")
        sys.exit(exit_codes.NOT_FOUND)
    console.print(f"[green]forked[/green] {src} -> {new_id} at {path}")


@template.command(
    "snapshot",
    help="Capture a running agent's state as a new template version.",
)
@click.argument("agent_name")
@click.option("--as", "target_id", required=True, help="<flavour>:<name>:v<n>")
@click.pass_context
def template_snapshot_cmd(
    ctx: click.Context, agent_name: str, target_id: str
) -> None:
    from . import snapshot as snapshot_mod

    cfg: config_mod.Config = ctx.obj["config"]
    try:
        identifiers.parse_template_id(target_id)
    except identifiers.IdentifierError as e:
        err.print(f"[red]error:[/red] {e}")
        sys.exit(exit_codes.TEMPLATE_SCHEMA)

    try:
        path = snapshot_mod.snapshot(
            cfg, agent_name=agent_name, target_template_id_str=target_id
        )
    except registry_mod.RegistryError as e:
        err.print(f"[red]error:[/red] {e}")
        sys.exit(exit_codes.NOT_FOUND)
    except snapshot_mod.SnapshotError as e:
        msg = str(e)
        if "flavour" in msg:
            err.print(f"[red]flavour mismatch:[/red] {msg}")
            sys.exit(exit_codes.FLAVOUR_MISMATCH)
        if "already exists" in msg:
            err.print(f"[red]error:[/red] {msg}")
            sys.exit(exit_codes.TEMPLATE_EXISTS)
        err.print(f"[red]snapshot error:[/red] {msg}")
        sys.exit(exit_codes.SNAPSHOT_FAILED)
    console.print(f"[green]snapshot written[/green]: {target_id} at {path}")


@template.command("test", help="Compile + spin a container against a template; record experimental on green.")
@click.argument("template_id")
@click.option(
    "--against-image",
    default=None,
    help="Override the template's preferred_image (e.g. openclaw:2026.5.8-r1).",
)
@click.option("--timeout", "timeout_seconds", default=60, type=int, help="Readyz wait timeout.")
@click.pass_context
def template_test_cmd(
    ctx: click.Context,
    template_id: str,
    against_image: Optional[str],
    timeout_seconds: int,
) -> None:
    cfg: config_mod.Config = ctx.obj["config"]
    try:
        tid = identifiers.parse_template_id(template_id)
        if against_image is not None:
            identifiers.parse_image_ref(against_image)
    except identifiers.IdentifierError as e:
        err.print(f"[red]error:[/red] {e}")
        sys.exit(exit_codes.TEMPLATE_SCHEMA)

    try:
        result = test_runner_mod.run_template_test(
            cfg,
            template_id_str=template_id,
            against_image_str=against_image,
            timeout_seconds=timeout_seconds,
        )
    except test_runner_mod.TestRunnerError as e:
        err.print(f"[red]test runner error:[/red] {e}")
        sys.exit(exit_codes.TEST_FAILED)

    image_field = against_image or "(preferred_image)"
    if not result.success:
        err.print(
            f"[red]template test failed[/red] for {template_id} against {image_field} "
            f"(readyz={result.readyz_status})"
        )
        if result.container_state:
            err.print(f"  container: {result.container_state}")
        if result.log_path:
            err.print(f"  logs: {result.log_path}")
        sys.exit(exit_codes.TEST_FAILED)

    # On green, upsert experimental matrix entry
    image_ref = identifiers.parse_image_ref(
        against_image
        if against_image
        else _resolve_preferred_image(cfg, tid)
    )
    matrix_template_field = f"{tid.name}:v{tid.version}"
    matrix_mod.upsert(
        cfg.matrix_path(),
        matrix_mod.MatrixEntry(
            flavour=tid.flavour,
            image=image_ref.image_version,
            template=matrix_template_field,
            status="experimental",
            tested_at=matrix_mod.now_iso(),
            test_agent="",
            notes=f"template test passed in {result.duration_seconds}s",
        ),
    )
    console.print(
        f"[green]template test passed[/green]: {template_id} against "
        f"{image_ref}; matrix entry marked experimental"
    )


def _resolve_preferred_image(cfg: config_mod.Config, tid: identifiers.TemplateID) -> str:
    tpl = registry_mod.load_template(cfg, tid.flavour, tid.name, tid.version)
    if not tpl.preferred_image:
        raise click.ClickException(
            f"template {tid} has no preferred_image and --against-image not supplied"
        )
    return tpl.preferred_image


@template.command("bless", help="Promote an experimental matrix entry to blessed.")
@click.argument("template_id")
@click.option(
    "--against-image",
    default=None,
    help="Image to bless this template against (e.g. openclaw:2026.5.5-r1).",
)
@click.option("--notes", default="", help="Free-form bless notes.")
@click.pass_context
def template_bless_cmd(
    ctx: click.Context,
    template_id: str,
    against_image: Optional[str],
    notes: str,
) -> None:
    cfg: config_mod.Config = ctx.obj["config"]
    try:
        tid = identifiers.parse_template_id(template_id)
        if against_image:
            image_ref = identifiers.parse_image_ref(against_image)
        else:
            image_ref = identifiers.parse_image_ref(_resolve_preferred_image(cfg, tid))
    except identifiers.IdentifierError as e:
        err.print(f"[red]error:[/red] {e}")
        sys.exit(exit_codes.TEMPLATE_SCHEMA)

    matrix_template_field = f"{tid.name}:v{tid.version}"
    try:
        entry = bless_mod.bless(
            cfg,
            flavour=tid.flavour,
            image=image_ref.image_version,
            template=matrix_template_field,
            notes=notes,
        )
    except bless_mod.BlessError as e:
        err.print(f"[red]bless error:[/red] {e}")
        sys.exit(exit_codes.MATRIX_BROKEN)
    console.print(
        f"[green]blessed[/green]: ({tid.flavour}, {image_ref.image_version}, "
        f"{matrix_template_field}) — tested_at={entry.tested_at}"
    )


@template.command("diff", help="Human-readable diff of two resolved template chains.")
@click.argument("template_a")
@click.argument("template_b")
@click.pass_context
def template_diff_cmd(ctx: click.Context, template_a: str, template_b: str) -> None:
    cfg: config_mod.Config = ctx.obj["config"]
    try:
        a_id = identifiers.parse_template_id(template_a)
        b_id = identifiers.parse_template_id(template_b)
    except identifiers.IdentifierError as e:
        err.print(f"[red]error:[/red] {e}")
        sys.exit(exit_codes.TEMPLATE_SCHEMA)

    try:
        a = resolver_mod.resolve(cfg, a_id)
        b = resolver_mod.resolve(cfg, b_id)
    except resolver_mod.CycleError as e:
        err.print(f"[red]cycle:[/red] {e}")
        sys.exit(exit_codes.CYCLE)
    except resolver_mod.FlavourMismatchError as e:
        err.print(f"[red]flavour mismatch:[/red] {e}")
        sys.exit(exit_codes.FLAVOUR_MISMATCH)
    except registry_mod.RegistryError as e:
        err.print(f"[red]registry error:[/red] {e}")
        sys.exit(exit_codes.NOT_FOUND)

    console.print(diff_mod.format_diff(a, b))


@template.command("edit", help="Open a template YAML in $EDITOR.")
@click.argument("template_id")
@click.pass_context
def template_edit_cmd(ctx: click.Context, template_id: str) -> None:
    cfg: config_mod.Config = ctx.obj["config"]
    try:
        tid = identifiers.parse_template_id(template_id)
    except identifiers.IdentifierError as e:
        err.print(f"[red]error:[/red] {e}")
        sys.exit(exit_codes.TEMPLATE_SCHEMA)
    path = cfg.template_path(tid.flavour, tid.name, tid.version)
    if not path.is_file():
        err.print(f"[red]error:[/red] template not found: {path}")
        sys.exit(exit_codes.NOT_FOUND)
    click.edit(filename=str(path))


@cli.command("compile", help="Compile one agent (or --all) into deployable artifacts.")
@click.argument("agent_name", required=False)
@click.option("--all", "compile_all", is_flag=True, help="Compile every agent in the registry.")
@click.option(
    "--allow-experimental",
    is_flag=True,
    help="Suppress experimental-matrix warning and proceed.",
)
@click.pass_context
def compile_cmd(
    ctx: click.Context,
    agent_name: Optional[str],
    compile_all: bool,
    allow_experimental: bool,
) -> None:
    cfg: config_mod.Config = ctx.obj["config"]

    if compile_all and agent_name:
        err.print("[red]error:[/red] specify either <agent_name> or --all, not both")
        sys.exit(exit_codes.CONFIG)
    if not compile_all and not agent_name:
        err.print("[red]error:[/red] specify an agent name or pass --all")
        sys.exit(exit_codes.CONFIG)

    if compile_all:
        try:
            reg = registry_mod.load_agent_registry(cfg)
        except registry_mod.RegistryError as e:
            err.print(f"[red]error:[/red] {e}")
            sys.exit(exit_codes.NOT_FOUND)
        targets = [a["name"] for a in (reg.get("agents") or [])]
    else:
        targets = [agent_name]  # type: ignore[list-item]

    any_failed = False
    for name in targets:
        try:
            result = compile_mod.compile_agent(
                cfg, name, allow_experimental=allow_experimental
            )
        except registry_mod.RegistryError as e:
            err.print(f"[red]{name}: not found:[/red] {e}")
            any_failed = True
            sys.exit(exit_codes.NOT_FOUND)
        except compile_mod.FlavourMismatchError as e:
            err.print(f"[red]{name}: flavour mismatch:[/red] {e}")
            sys.exit(exit_codes.FLAVOUR_MISMATCH)
        except compile_mod.MatrixBrokenError as e:
            err.print(f"[red]{name}: matrix broken:[/red] {e}")
            sys.exit(exit_codes.MATRIX_BROKEN)
        except compile_mod.CompileError as e:
            err.print(f"[red]{name}: compile error:[/red] {e}")
            sys.exit(exit_codes.WRITE_FAILED)

        console.print(
            f"[green]compiled[/green] {result.agent_name} -> "
            f"{result.artifact_root} ({len(result.files)} files)"
        )

    if any_failed:
        sys.exit(exit_codes.WRITE_FAILED)


@cli.command("test", help="Compile + spin a container against a real agent (no matrix write).")
@click.argument("agent_name")
@click.option("--timeout", "timeout_seconds", default=60, type=int)
@click.pass_context
def agent_test_cmd(ctx: click.Context, agent_name: str, timeout_seconds: int) -> None:
    cfg: config_mod.Config = ctx.obj["config"]
    try:
        agent = registry_mod.get_agent(cfg, agent_name)
    except registry_mod.RegistryError as e:
        err.print(f"[red]error:[/red] {e}")
        sys.exit(exit_codes.NOT_FOUND)

    # Use the same runner but pass the real agent — re-use the path that compile_pipeline
    # already takes. We still write to a temp artifact root and don't touch the matrix.
    import uuid as _uuid

    from . import compile as _compile

    test_uuid = _uuid.uuid4().hex[:8]
    test_root = cfg.registry_root / ".test" / f"{agent_name}-{test_uuid}"
    test_root.mkdir(parents=True, exist_ok=True)
    artifact_root = test_root / "artifacts"
    try:
        result = _compile.compile_pipeline(
            cfg,
            agent,
            allow_experimental=True,
            artifact_root_override=artifact_root,
            emit_compose=False,
        )
    except (_compile.CompileError, registry_mod.RegistryError) as e:
        err.print(f"[red]compile error:[/red] {e}")
        sys.exit(exit_codes.WRITE_FAILED)

    try:
        run_result = test_runner_mod._run_container(
            cfg,
            flavour=result.flavour,
            image_version=result.image_version,
            artifact_root=artifact_root,
            test_uuid=test_uuid,
            stub_agent=agent,
            timeout_seconds=timeout_seconds,
        )
    except test_runner_mod.TestRunnerError as e:
        err.print(f"[red]test runner error:[/red] {e}")
        sys.exit(exit_codes.TEST_FAILED)

    if not run_result.success:
        err.print(
            f"[red]agent test failed[/red] for {agent_name} "
            f"(readyz={run_result.readyz_status})"
        )
        if run_result.container_state:
            err.print(f"  container: {run_result.container_state}")
        if run_result.log_path:
            err.print(f"  logs: {run_result.log_path}")
        sys.exit(exit_codes.TEST_FAILED)
    console.print(
        f"[green]agent test passed[/green]: {agent_name} "
        f"(duration={run_result.duration_seconds}s)"
    )


@cli.command("verify", help="Check that the agent's artifacts are current and matrix is blessed.")
@click.argument("agent_name")
@click.pass_context
def verify_cmd(ctx: click.Context, agent_name: str) -> None:
    cfg: config_mod.Config = ctx.obj["config"]
    result = verify_mod.verify_agent(cfg, agent_name)
    for w in result.warnings:
        console.print(f"[yellow]warning:[/yellow] {w}")
    for f in result.failures:
        err.print(f"[red]fail:[/red] {f}")
    if result.ok:
        console.print(f"[green]verify ok[/green]: {agent_name}")
        sys.exit(exit_codes.SUCCESS)
    sys.exit(exit_codes.NOT_FOUND)


if __name__ == "__main__":
    cli()
