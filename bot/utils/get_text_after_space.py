def get_text_after_space(text: str) -> str | None:
    if not text:
        return None

    command_end_index = text.find(" ")
    if command_end_index == -1:
        return None

    return text[command_end_index + 1 :]
