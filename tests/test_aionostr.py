from click.testing import CliRunner

from electrum_aionostr import cli


def test_command_line_interface():
    """Test the CLI."""
    runner = CliRunner()
    result = runner.invoke(cli.main)
    assert result.exit_code == 2  # no_args_is_help will result in 2, since https://github.com/pallets/click/pull/1489
    assert 'Console script for aionostr' in result.output
    help_result = runner.invoke(cli.main, ['--help'])
    assert help_result.exit_code == 0
    assert '--help  Show this message and exit.' in help_result.output
