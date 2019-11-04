import pytest
from click.testing import CliRunner

import datacube_alchemist.cli


@pytest.fixture
def run_alchemist():
    """
    A helpful fixture for running a a click CLI from within pytest
    """

    def _run_cli(*opts,
                 catch_exceptions=False,
                 expect_success=True,
                 cli_method=datacube_alchemist.cli.cli):
        exe_opts = []
        exe_opts.extend(opts)

        runner = CliRunner()
        result = runner.invoke(
            cli_method,
            exe_opts,
            catch_exceptions=catch_exceptions
        )
        if expect_success:
            assert 0 == result.exit_code, "Error for %r. output: %r" % (opts, result.output)
        return result

    return _run_cli

