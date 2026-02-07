import subprocess
import os
import tempfile
from app.services.resource_limits import run_with_limits


def _convert_file_worker(input_path: str, convert_to: str) -> str:
    """
    Worker function that performs the actual file conversion.
    This runs in a separate process with resource limits.
    """
    output_dir = tempfile.gettempdir()
    os.makedirs(output_dir, exist_ok=True)

    cmd = [
        "soffice",
        "--headless",
        "--convert-to",
        convert_to,
        "--outdir",
        output_dir,
        input_path,
    ]

    subprocess.run(
        cmd,
        check=True,
        start_new_session=os.name != "nt",
    )

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    ext = convert_to.split(":")[0]
    converted_path = os.path.join(output_dir, f"{base_name}.{ext}")

    if not os.path.exists(converted_path):
        raise FileNotFoundError(
            f"Conversion failed: output file not created at {converted_path}"
        )

    return converted_path


def convert_file(input_path: str, convert_to: str) -> str:
    """
    Convert a file using LibreOffice with resource limits.

    This function runs the conversion in a separate process with:
    - Memory limit (512 MB)
    - CPU time limit (30 seconds)
    - Total timeout (45 seconds)

    Args:
        input_path: Path to the input file
        convert_to: Target format (e.g., 'pdf', 'docx')

    Returns:
        Path to the converted file

    Raises:
        TimeoutError: If conversion exceeds time limit
        MemoryLimitError: If conversion exceeds memory limit
        ResourceLimitError: If conversion fails due to resource limits
    """
    return run_with_limits(_convert_file_worker, input_path, convert_to)
