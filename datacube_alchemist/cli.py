import click
import sys
import time

from datacube.ui import click as ui
from datacube_alchemist._utils import _configure_logger
import structlog
from datacube_alchemist.worker import Alchemist, get_messages
from odc.aws.queue import get_queue

_LOG = structlog.get_logger()

# Define common options for all the commands
queue_option = click.option(
    "--queue", "-q", help="Name of an AWS SQS Message Queue", required=True
)
uuid_option = click.option(
    "--uuid", "-u", required=True, help="UUID of the scene to be processed"
)
queue_timeout = click.option(
    "--queue-timeout",
    "-s",
    type=int,
    help="The SQS message Visibility Timeout in seconds, default is 600, or 10 minutes.",
    default=600,
)
limit_option = click.option(
    "--limit",
    "-l",
    type=int,
    help="For testing, limit the number of tasks to create or process.",
    default=None,
)
product_limit_option = click.option(
    "--product-limit",
    "-p",
    type=int,
    help="For testing, limit the number of datasets per product.",
    default=None,
)
config_file_option = click.option(
    "--config-file",
    "-c",
    required=True,
    help="The path (URI or file) to a config file to use for the job",
)
dryrun_option = click.option(
    "--dryrun",
    "--no-dryrun",
    is_flag=True,
    default=False,
    help="Don't actually do real work",
)
sns_arn_option = click.option(
    "--sns-arn",
    default=None,
    help="Publish resulting STAC document to an SNS",
)


def _print_version(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    from datacube_alchemist import __version__ as alchemist_version
    from datacube import __version__ as datacube_version

    click.echo(f"datacube-alchemist, version {alchemist_version}")
    click.echo(f"Open Data Cube core, version {datacube_version}")
    ctx.exit()


def cli_with_envvar_handling():
    cli(auto_envvar_prefix="ALCHEMIST")


@click.group(context_settings=dict(max_content_width=120))
@click.option(
    "--version",
    is_flag=True,
    callback=_print_version,
    expose_value=False,
    is_eager=True,
)
def cli():
    """
    Transform Datasets from the Open Data Cube into a new type of Dataset
    """
    # Set up opinionated logging
    _configure_logger()


@cli.command()
@config_file_option
@uuid_option
@dryrun_option
def run_one(config_file, uuid, dryrun):
    """
    Run with the config file for one input_dataset (by UUID)
    """
    alchemist = Alchemist(config_file=config_file)
    task = alchemist.generate_task_by_uuid(uuid)
    if task:
        alchemist.execute_task(task, dryrun)
    else:
        _LOG.error(f"Failed to generate a task for UUID {uuid}")
        sys.exit(1)


@cli.command()
@config_file_option
@ui.parsed_search_expressions
@limit_option
@dryrun_option
def run_many(config_file, expressions, limit, dryrun):
    """
    Run Alchemist with the config file on all the Datasets matching an ODC query expression
    """
    # Load Configuration file
    alchemist = Alchemist(config_file=config_file)

    tasks = alchemist.generate_tasks(expressions, limit=limit)

    executed = 0

    for task in tasks:
        alchemist.execute_task(task, dryrun)
        executed += 1

    if executed == 0:
        _LOG.error("Failed to generate any tasks")
        sys.exit(1)


@cli.command()
@config_file_option
@queue_option
@limit_option
@queue_timeout
@dryrun_option
@sns_arn_option
def run_from_queue(config_file, queue, limit, queue_timeout, dryrun, sns_arn):
    """
    Process messages from the given queue
    """

    alchemist = Alchemist(config_file=config_file)

    tasks_and_messages = alchemist.get_tasks_from_queue(queue, limit, queue_timeout)

    errors = 0
    successes = 0

    for task, message in tasks_and_messages:
        try:
            alchemist.execute_task(task, dryrun, sns_arn)
            message.delete()
            successes += 1

        except Exception as e:
            errors += 1
            _LOG.error(
                f"Failed to run transform {alchemist.transform_name} on dataset {task.dataset.id} with error {e}"
            )

    if errors > 0:
        _LOG.error(f"There were {errors} tasks that failed to execute.")
        sys.exit(errors)
    if limit and (errors + successes) < limit:
        _LOG.warning(
            f"There were {errors} tasks that failed and {successes} successful tasks"
            ", which is less than the limit specified"
        )


@cli.command()
@config_file_option
@queue_option
@ui.parsed_search_expressions
@limit_option
@product_limit_option
def add_to_queue(config_file, queue, expressions, limit, product_limit):
    """
    Search for Datasets and enqueue Tasks into an AWS SQS Queue for later processing.
    """

    start_time = time.time()

    alchemist = Alchemist(config_file=config_file)
    n_messages = alchemist.enqueue_datasets(queue, expressions, limit, product_limit)

    _LOG.info(f"Pushed {n_messages} items in {time.time() - start_time:.2f}s.")


@cli.command()
@queue_option
@limit_option
@click.option("--to-queue", "-t", help="Url of SQS Queue to move to", required=True)
def redrive_to_queue(queue, to_queue, limit):
    """
    Redrives all the messages from the given sqs queue to the destination
    """

    dead_queue = get_queue(queue)
    alive_queue = get_queue(to_queue)

    messages = get_messages(dead_queue)

    count = 0

    for message in messages:
        response = alive_queue.send_message(MessageBody=message.body)
        if response["ResponseMetadata"]["HTTPStatusCode"] == 200:
            message.delete()
            count += 1
            if limit and count >= limit:
                break
        else:
            _LOG.error(f"Unable to send message {message} to queue")
    _LOG.info(f"Completed sending {count} messages to the queue")


if __name__ == "__main__":
    cli_with_envvar_handling()
