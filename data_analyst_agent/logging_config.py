"""Structured logging configuration for data_analyst_agent."""
import logging
import os
import sys
from pythonjsonlogger import jsonlogger


def setup_logging(name: str = "data_analyst_agent") -> logging.Logger:
    """
    Set up structured JSON logging for the application.
    
    Args:
        name: Logger name (default: "data_analyst_agent")
    
    Returns:
        Configured logger instance
    """
    level = os.getenv("LOG_LEVEL", "INFO")
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Avoid duplicate handlers if called multiple times
    if logger.handlers:
        return logger
    
    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger


# Default logger instance
logger = setup_logging()
