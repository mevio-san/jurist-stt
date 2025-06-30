from collections import deque
import threading
import boto3
import botocore

class CloudWatchLoggerWorker(threading.Thread):
  """
  A worker thread that logs messages to AWS CloudWatch Logs asynchronously.
  """
  def __init__(
    self,
    aws_region,
    aws_access_key,
    aws_secret_key,
    log_group_name,
    log_stream_name_fn,
    max_buffer_len=16384,
    flush_interval=1):
    """
    Initializes the CloudWatch logger worker.

    Parameters:
    - aws_region: AWS region name.
    - aws_access_key: AWS access key ID.
    - aws_secret_key: AWS secret access key.
    - log_group_name: Name of the CloudWatch log group.
    - log_stream_name_fn: Function that generates the log stream name.
    - max_buffer_len: Maximum buffer size for storing log messages.
    - flush_interval: Time interval (in seconds) to flush logs.
    """
    super().__init__()
    self._aws_region = aws_region
    self._aws_access_key = aws_access_key
    self._aws_secret_key = aws_secret_key
    self._log_group_name = log_group_name
    self._log_stream_name_fn = log_stream_name_fn
    self._last_log_stream_name = None

    # Create the CloudWatch client; if it fails, terminate the thread
    if not self._create_cloudwatch_client():
      self.kill()
      return
    self._buffer = deque(maxlen=max_buffer_len) # Buffer for storing logs before flushing
    self._flush_interval = flush_interval # Interval between log flushes
    self._kill_evt = threading.Event() # Event to signal thread termination

  def _create_cloudwatch_client(self):
    """
    Creates a CloudWatch Logs client using the provided AWS credentials.
    
    Returns:
    - True if the client was created successfully, False otherwise.
    """
    try:
      self._client = boto3.client(
        'logs',
        region_name=self._aws_region,
        aws_access_key_id=self._aws_access_key,
        aws_secret_access_key=self._aws_secret_key
      )
      return True
    except Exception as e:
      self._client = None
      return False

  def append(self, msg):
    """
    Adds a log message to the buffer.

    Parameters:
    - msg: The log message to be added.
    """
    self._buffer.appendleft(msg)

  def run(self):
    """
    Main loop of the logging worker. Periodically flushes logs to CloudWatch.
    Terminates when the kill event is set.
    """
    while True:
      self._flush()
      if self._kill_evt.wait(self._flush_interval): # Check if thread should stop
        break
    self._flush() # Final flush before exiting

  def _flush(self):
    """
    Flushes buffered log messages to AWS CloudWatch Logs.
    """
    if self._client == None:
      return

    # Kill the thread if the main thread is no longer running
    if not threading.main_thread().is_alive():
      self.kill()

    # If the log stream name has changed, create a new log stream
    log_stream_name = self._log_stream_name_fn()
    if self._last_log_stream_name != log_stream_name:
      self._create_log_stream(log_stream_name)
      self._last_log_stream_name = log_stream_name

    msgs = []
    while self._buffer:
      msgs.append(self._buffer.pop())
    
    if len(msgs) == 0:
      return

    try:
      # Send logs to CloudWatch
      self._client.put_log_events(
        logGroupName=self._log_group_name,
        logStreamName=log_stream_name,
        logEvents=msgs
      )
    except Exception as e:
      pass # Ignore exceptions to prevent worker crash

  def _create_log_stream(self, log_stream_name):
    """
    Creates a new log stream in the specified log group.

    Parameters:
    - log_stream_name: Name of the log stream to be created.

    Returns:
    - True if creation is successful, False otherwise.
    """
    try:
      self._client.create_log_stream(
        logGroupName=self._log_group_name,
        logStreamName=log_stream_name
      )
      return True
    except:
      return False

  def kill(self):
    """
    Signals the thread to terminate gracefully.
    """
    self._kill_evt.set()
