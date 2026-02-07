import multiprocessing
import sys
from typing import TYPE_CHECKING, Any, Callable, TypeVar
from functools import wraps

from app.settings import settings


if sys.platform != "win32" or TYPE_CHECKING:
    import signal
    import resource


T = TypeVar("T")


class ResourceLimitError(Exception):
    """Raised when a resource limit is exceeded."""

    pass


class TimeoutError(ResourceLimitError):
    """Raised when operation exceeds time limit."""

    pass


class MemoryLimitError(ResourceLimitError):
    """Raised when operation exceeds memory limit."""

    pass


def _limit_resources() -> None:
    """
    Set resource limits for the current process.
    Called at the start of worker processes.
    """
    if sys.platform == "win32":
        return

    # Limit virtual memory (address space)
    resource.setrlimit(
        resource.RLIMIT_AS, (settings.MAX_PROCESS_MEMORY, settings.MAX_PROCESS_MEMORY)
    )

    # Limit CPU time
    resource.setrlimit(
        resource.RLIMIT_CPU,
        (settings.MAX_PROCESS_CPU_TIME, settings.MAX_PROCESS_CPU_TIME),
    )

    # Limit number of open files
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))

    # Limit core dump size to 0
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _worker_wrapper(
    func: Callable[..., T],
    queue: multiprocessing.Queue,  # type: ignore[type-arg]
    *args: Any,
    **kwargs: Any,
) -> None:
    """
    Wrapper function that runs in the worker process.
    Sets resource limits and executes the target function.
    """
    try:
        _limit_resources()
        result = func(*args, **kwargs)
        queue.put({"success": True, "result": result})
    except MemoryError:
        queue.put(
            {"success": False, "error": "Memory limit exceeded", "type": "memory"}
        )
    except Exception as e:
        queue.put({"success": False, "error": str(e), "type": type(e).__name__})


def run_with_limits(
    func: Callable[..., T], *args: Any, timeout: int | None = None, **kwargs: Any
) -> T:
    """
    Run a function in a separate process with resource limits.

    Args:
        func: Function to execute
        *args: Positional arguments for func
        timeout: Maximum time in seconds (default: MAX_CONVERSION_TIME from settings)
        **kwargs: Keyword arguments for func

    Returns:
        Result from func

    Raises:
        TimeoutError: If execution exceeds timeout
        MemoryLimitError: If execution exceeds memory limit
        ResourceLimitError: If execution is killed by resource limits
        Exception: Any exception raised by func
    """
    if timeout is None:
        timeout = settings.MAX_CONVERSION_TIME

    queue: multiprocessing.Queue = multiprocessing.Queue()  # type: ignore[type-arg]
    process = multiprocessing.Process(
        target=_worker_wrapper, args=(func, queue, *args), kwargs=kwargs
    )

    process.start()
    process.join(timeout=timeout)

    if process.is_alive():
        # Process exceeded timeout
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join()
        raise TimeoutError(f"Operation exceeded {timeout} second timeout")

    if process.exitcode != 0:
        if sys.platform == "win32":
            raise ResourceLimitError(
                f"Process terminated with exit code {process.exitcode}"
            )

        # Process was killed (likely by resource limit)
        if process.exitcode == -signal.SIGXCPU:
            raise ResourceLimitError("CPU time limit exceeded")
        elif process.exitcode == -signal.SIGKILL or process.exitcode == -signal.SIGTERM:
            raise MemoryLimitError("Memory limit exceeded or process killed")
        else:
            raise ResourceLimitError(
                f"Process terminated with exit code {process.exitcode}"
            )

    # Get result from queue
    if queue.empty():
        raise ResourceLimitError("Process terminated without returning result")

    response = queue.get()

    if not response["success"]:
        error_type = response.get("type", "Unknown")
        error_msg = response.get("error", "Unknown error")

        if error_type == "memory":
            raise MemoryLimitError(error_msg)
        else:
            # Re-raise the original exception type if possible
            raise ResourceLimitError(f"{error_type}: {error_msg}")

    result: T = response["result"]

    return result


def validate_file_size(file_size: int | None) -> None:
    """
    Validate that file size is within acceptable limits.

    Args:
        file_size: File size in bytes (None if unknown)

    Raises:
        ResourceLimitError: If file size exceeds MAX_FILE_DOWNLOAD_SIZE
    """
    if file_size is not None and file_size > settings.MAX_FILE_DOWNLOAD_SIZE:
        size_mb = file_size / (1024 * 1024)
        limit_mb = settings.MAX_FILE_DOWNLOAD_SIZE / (1024 * 1024)
        raise ResourceLimitError(
            f"File size ({size_mb:.1f} MB) exceeds maximum allowed size ({limit_mb:.1f} MB)"
        )


def safe_file_operation(
    timeout: int | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to run file operations with resource limits.

    Usage:
        @safe_file_operation(timeout=30)
        def process_file(path: str) -> str:
            # ... heavy processing ...
            return result

    Args:
        timeout: Maximum execution time in seconds
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            return run_with_limits(func, *args, timeout=timeout, **kwargs)

        return wrapper

    return decorator
