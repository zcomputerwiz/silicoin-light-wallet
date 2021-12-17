from pathlib import Path
import click
from chia.cmds.transition_funcs import transition_func


@click.command("transition", short_help="Transition blockchain database to new schema")
@click.option("--input", default=None, type=click.Path(), help="specify input database file")
@click.option("--output", default=None, type=click.Path(), help="specify output database file")
@click.pass_context
def transition_cmd(ctx: click.Context, **kwargs):

    in_db_path = kwargs.get("input")
    out_db_path = kwargs.get("output")
    transition_func(
        Path(ctx.obj["root_path"]),
        None if in_db_path is None else Path(in_db_path),
        None if out_db_path is None else Path(out_db_path),
    )


if __name__ == "__main__":
    from chia.util.default_root import DEFAULT_ROOT_PATH

    transition_func(DEFAULT_ROOT_PATH)
