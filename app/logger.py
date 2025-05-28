"""This module provides functionality for logging with color-coded output using the Singleton design pattern.

Classes:
    Colors: Defines ANSI color codes for coloring terminal text.
    SingletonLogger: A thread-safe singleton logger that adds color to log messages.
"""

import inspect
import logging
import os
import threading


# Rest of the code follows...
class Colors:
    """ANSI color codes for formatting console output."""

    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    PURPLE = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    RESET = "\033[0m"


class SingletonLogger:
    """A singleton logger class with color-coded output."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """Create a new instance if one does not exist."""
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize(*args, **kwargs)
        return cls._instance

    def _initialize(self, level=logging.DEBUG):
        """Initialize the logger with a specified logging level."""
        self.logger = logging.getLogger("SingletonLogger")
        self.logger.setLevel(level)
        self.logger.propagate = False

        if not self.logger.handlers:
            formatter = self._get_colored_formatter()

            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

    def _get_colored_formatter(self):
        """Return a logging formatter that adds color to log messages."""

        class ColoredFormatter(logging.Formatter):
            """A logging formatter that adds color to log messages."""

            def format(self, record):
                """Format the log record with color and module information."""
                frame = inspect.stack()[8]  # Adjust index to reach the caller
                module = inspect.getmodule(frame[0])
                module_name = module.__name__ if module else ""
                class_name = ""
                if "self" in frame[0].f_locals:
                    class_name = frame[0].f_locals["self"].__class__.__name__
                function_name = frame[3]
                experiment_id = os.getenv("experiment_id", None)

                caller_name = f"{experiment_id}.{module_name}.{class_name}.{function_name}".strip(
                    "."
                )

                color = Colors.WHITE  # default to white
                if record.levelno == logging.DEBUG:
                    color = Colors.CYAN
                elif record.levelno == logging.INFO:
                    color = Colors.GREEN
                elif record.levelno == logging.WARNING:
                    color = Colors.YELLOW
                elif record.levelno == logging.ERROR:
                    color = Colors.RED
                elif record.levelno == logging.CRITICAL:
                    color = Colors.PURPLE

                record.msg = f"{color}{record.msg}{Colors.RESET}"
                record.name = caller_name
                return super().format(record)

        return ColoredFormatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    def set_level(self, level):
        """Set the logging level."""
        self.logger.setLevel(level)

    def get_logger(self):
        """Retrieve the logger instance."""
        return self.logger
