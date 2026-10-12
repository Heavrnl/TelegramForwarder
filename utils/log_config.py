import os
import logging
from pathlib import Path
from dotenv import load_dotenv

def setup_logging():
    """
    Configure the logging system to output all logs to stdout,
    where they will be collected and managed by Docker.
    """
    # Load environment variables
    load_dotenv()

    # Create the root logger
    root_logger = logging.getLogger()

    # Set log level — INFO by default
    root_logger.setLevel(logging.INFO)

    # Create a handler to output logs to the console
    console_handler = logging.StreamHandler()

    # Create a formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Attach the formatter to the handler
    console_handler.setFormatter(formatter)

    # Attach the handler to the root logger
    root_logger.addHandler(console_handler)

    # Return the configured logger
    return root_logger
