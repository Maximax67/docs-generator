from aiogram.filters.callback_data import CallbackData


class MainCallback(CallbackData, prefix="m"):
    action: str
    q: str


class GenerationCallback(CallbackData, prefix="g"):
    action: str
    q: str


class SavedDataCallback(CallbackData, prefix="s"):
    action: str
    q: str
