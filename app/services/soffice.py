import subprocess
import os
import tempfile


def convert_file(input_path: str, convert_to: str) -> str:
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

    subprocess.run(cmd, check=True)

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    ext = convert_to.split(":")[0]
    converted_path = os.path.join(output_dir, f"{base_name}.{ext}")

    return converted_path
