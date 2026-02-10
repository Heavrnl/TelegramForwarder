import os
import logging
from pathlib import Path
from dotenv import load_dotenv

def setup_logging():
    """
    Configure the logging system, output all logs to stdout,
    collected and managed by Docker
    """
    # Load environment variables
    load_dotenv()

    # Create root logger
    root_logger = logging.getLogger()

    # Set log level - default to INFO level
    root_logger.setLevel(logging.INFO)

    # Create a handler to output logs to the console
    console_handler = logging.StreamHandler()

    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Add formatter to handler
    console_handler.setFormatter(formatter)

    # Add handler to root logger
    root_logger.addHandler(console_handler)

    # Return the configured logger
    return root_logger
