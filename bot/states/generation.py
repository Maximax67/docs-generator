from aiogram.fsm.state import State, StatesGroup


class GenerationStates(StatesGroup):
    select_root_folder = State()
    selecting = State()
    document_preview = State()
    filling_input_variable = State()
    filling_multichoise_variable = State()
    results = State()
