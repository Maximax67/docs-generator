from aiogram.fsm.state import State, StatesGroup


class SavedDataStates(StatesGroup):
    view_all = State()
    view_variable = State()
