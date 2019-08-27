#!/usr/bin/env python3
"""


"""
import os
import structlog
import boto3
import cloudpickle

from datacube_alchemist.upload import S3Upload
from datacube_alchemist.worker import Alchemist, execute_task

_LOG = structlog.get_logger()

def add_to_queue(config_file, message_queue, expressions, environment=None, limit=None):

    # Set up the queue
    sqs = boto3.resource('sqs')
    queue = sqs.get_queue_by_name(QueueName=message_queue)

    # Load Configuration file
    alchemist = Alchemist(config_file=config_file, dc_env=environment)

    tasks = alchemist.generate_tasks(expressions, limit=limit)
    for task in tasks:
        pickled_task = cloudpickle.dumps(task)
        atts = {'pickled_task': {'BinaryValue': pickled_task, 'DataType': 'Binary'}}
        # The information is in the pickled_task message attribute
        # The message body is not used by the s/w
        body = task.dataset.local_uri if task.dataset.local_uri is not None else 'local_uri is None'
        queue.send_message(MessageBody=body,  MessageAttributes=atts)

def pull_from_queue(message_queue, sqs_timeout=None, make_public=False):
    # Set up the queue
    sqs = boto3.resource('sqs')
    queue = sqs.get_queue_by_name(QueueName=message_queue)

    messages = queue.receive_messages(
        VisibilityTimeout=sqs_timeout,
        MaxNumberOfMessages=1,
        MessageAttributeNames=['All']
    )
    if len(messages) > 0:
        message = messages[0]
        pickled_task = message.message_attributes['pickled_task']['BinaryValue']
        task = cloudpickle.loads(pickled_task)
        s3ul = S3Upload(task.settings.output.location)
        # make location local if the location is S3
        task.settings.output.location = s3ul.location
        _LOG.info("Found task to process: {}".format(task))
        execute_task(task)
        s3ul.upload_if_needed(make_public)

        message.delete()
        _LOG.info("SQS message deleted")
    else:
        _LOG.warning("No messages!")


def run_command():
    """
    Use environment settings to call functions.

    :return:
    """

    sqs_queue = os.getenv('SQS_QUEUE')
    command = os.getenv('COMMAND')
    if command == 'pull_from_queue':
        sqs_timeout_sec = int(os.getenv('SQS_TIMEOUT_SEC', '500'))
        make_public = os.getenv('MAKE_PUBLIC', 'False')
        make_public = make_public in ['true', 'True']
        pull_from_queue(sqs_queue, sqs_timeout_sec, make_public)
    elif command == 'pull_from_queue':
        config_file = ''   #  Let's write this locally
        expressions = os.getenv('EXPRESSIONS', '')
        add_to_queue(config_file,
                     sqs_queue,
                     expressions,
                     environment=None, limit=None)

if __name__ == '__main__':
    run_command()