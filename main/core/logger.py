import json
import sys
import traceback
from typing import Callable, List
from uuid import uuid4
import datetime
import signal
import atexit
import logging
from fastapi.routing import APIRoute
from pydantic import BaseModel
from fastapi import HTTPException
from starlette.datastructures import QueryParams
from starlette.requests import Request
from starlette.responses import Response
from core.config import config

from core.cloudwatch_logger_worker import CloudWatchLoggerWorker
from core.cloudwatch_logger_handler import CloudWatchLoggerHandler, CloudWatchJsonFormatter


def get_log_stream_name():
    """
    Generates a log stream name based on the current UTC date.

    Returns:
    - A string representing the current date in 'YYYY-MM-DD' format.
    """
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")


def _register_signal(sig_no, cb_fn=None, append=True):
    """
    Registers a signal handler for the given signal number.

    Parameters:
    - sig_no: The signal number to handle (e.g., `signal.SIGTERM`).
    - cb_fn: Optional callback function to execute when the signal is received.
    - append: If True, preserves the previous signal handler and calls it after `cb_fn`.

    The new signal handler will:
    - Call `cb_fn`, if provided.
    - Call the previously registered handler if `append` is True.
    """
    prev_handler = signal.getsignal(sig_no) if append else None

    def new_signal_handler(sig_no, frame):
        if cb_fn:
            cb_fn(sig_no, frame)
        if prev_handler:
            prev_handler(sig_no, frame)

    signal.signal(sig_no, new_signal_handler)


def _create_default_logger():
    """
    Creates and returns a default logger object.
    """
    logger = logging.getLogger()
    console_formatter = logging.Formatter('%(levelname)s:\t[%(asctime)s] %(message)s [%(pathname)s:%(lineno)d]',
                                          datefmt='%Y-%m-%d %H:%M:%S')

    cloudwatch_formatter = CloudWatchJsonFormatter([
        "corr_id",
        "levelname",
        "message",
        "request_id",
        "url",
        "method",
        "query_params",
        "body",
        "response",
        "status_code"
    ], corr_id=True)

    # Set the log level
    logger.setLevel(config.get("log_level", logging.INFO))

    # Create the handlers
    console_handler = logging.StreamHandler()
    cloudwatch_worker = CloudWatchLoggerWorker(
        aws_region='us-east-1',
        aws_access_key=config.get("aws_access_key"),
        aws_secret_key=config.get("aws_secret_key"),
        log_group_name=config.get("log_group_name"),
        log_stream_name_fn=get_log_stream_name,
        max_buffer_len=16384,
        flush_interval=1
    )
    cloudwatch_handler = CloudWatchLoggerHandler(cloudwatch_worker)

    # Set the formatters
    console_handler.setFormatter(console_formatter)
    cloudwatch_handler.setFormatter(cloudwatch_formatter)

    # Add the handlers
    logger.addHandler(console_handler)
    logger.addHandler(cloudwatch_handler)

    def _gracefully_kill(sig_no, frame):
        logger.error(f'exception: {signal.strsignal(sig_no)}, frame: {frame}')
        cloudwatch_worker.kill()
        logger.removeHandler(cloudwatch_handler)

    def _program_termination():
        logger.info('program terminated')
        cloudwatch_worker.kill()
        logger.removeHandler(cloudwatch_handler)

    # Capture error/break signals
    _register_signal(signal.SIGABRT, cb_fn=_gracefully_kill)
    _register_signal(signal.SIGINT, cb_fn=_gracefully_kill)
    _register_signal(signal.SIGHUP, cb_fn=_gracefully_kill)
    _register_signal(signal.SIGSEGV, cb_fn=_gracefully_kill)
    _register_signal(signal.SIGTERM, cb_fn=_gracefully_kill)

    # Capture program termination
    atexit.register(_program_termination)

    return logger


logging.raiseExceptions = False

# Create the logger
logger = _create_default_logger()


#### DB REQUEST LOGGER ####

class AppLog(BaseModel):
    id: str = str(uuid4())
    date: datetime.datetime = None
    url: str
    method: str
    query_params: dict | None = None
    request: dict | None = None
    response: dict | None = None
    status_code: int | None = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @staticmethod
    async def insert_request(request: Request, ) -> str:
        """
        Insert the request and response into the database.
        :param request: Request from starlette.
        """
        # Generate an uuid4
        _id: str = str(uuid4())
        # Get the request path
        url: str = request.url.path
        # Query parameters (and add them to the URL)
        query_params: QueryParams = request.query_params
        # Method
        method: str = request.method
        # Get the request body
        _body: bytes or None = await request.body()
        body: dict or None = None
        # Can _body be decoded?
        if _body:
            try:
                body: dict or None = json.loads(_body)
            except json.JSONDecodeError:
                pass
        # Log it so it gets sent to cloudwatch
        logger.info("request", extra={
            "request_id": _id,
            "url": url,
            "method": method,
            "query_params": dict(query_params),
            "body": body
        })
        # Return the ID
        return _id

    @staticmethod
    async def insert_response(_id: str, response: Response, ) -> None:
        """
        Insert the response into the database.
        :param _id: The ID of the logger entry.
        :param response: Response from starlette.
        """
        # Get the status code
        status_code: int = response.status_code
        if getattr(response, "body", None):
            try:
                body: dict or None = json.loads(response.body)
            except:
                body: dict or None = None
        else:
            body: dict or None = None
        # Log it so it gets sent to cloudwatch
        logger.info('response', extra={
            "request_id": _id,
            "response": body,
            "status_code": status_code,
        })

    @staticmethod
    async def insert_error(_id: str, error: List[dict], status_code: int = 500) -> None:
        """
        Insert the error into the database.
        :param _id: The ID of the logger entry.
        :param error: Exception from starlette.
        """
        # Get the response body
        body: dict = {"error": error}
        # Log it so it gets sent to cloudwatch
        logger.error('response', extra={
            "request_id": _id,
            "response": body,
            "status_code": status_code,
        })


class LoggingRoute(APIRoute):
    @staticmethod
    def format_traceback(exc_type, exc_value, exc_traceback) -> List[dict]:
        """
        This function formats the traceback details into a list of dictionaries, for easier reading in mongo
        """
        # Initialize an empty list to hold formatted traceback details
        traceback_details = []

        # Extract traceback details using traceback.extract_tb
        for filename, line_number, function_name, text in traceback.extract_tb(exc_traceback):
            traceback_details.append({
                "filename": filename,
                "line_number": line_number,
                "function_name": function_name,
                "text": text
            })

        # Add exception type and value to the last entry in the list
        if traceback_details:
            traceback_details[-1]["exception_type"] = str(exc_type.__name__)
            traceback_details[-1]["exception_value"] = str(exc_value)
        # Return the formatted list
        return traceback_details

    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            """
            Handle the request and response logging.
            :param request: Request from starlette.
            :return: the original response.
            """
            # Save the request
            _id: str = await AppLog.insert_request(request=request)
            # Get the response
            try:
                response: Response = await original_route_handler(request)
            except HTTPException as e:
                # Log status code if it's from abort (or any HTTPException)
                await AppLog.insert_error(
                    _id=_id,
                    error=self.format_traceback(*sys.exc_info()),
                    status_code=e.status_code
                )
                raise e
            except Exception as e:
                # If there is an exception, save it
                await AppLog.insert_error(_id=_id, error=self.format_traceback(*sys.exc_info()), )
                raise e
            # And save it

            await AppLog.insert_response(_id=_id, response=response)
            # Return the original response
            return response

        return custom_route_handler
