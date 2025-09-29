from aiogram.fsm.state import StatesGroup, State

class MainStates(StatesGroup):
    generation = State()
    feedback = State()
    statistics = State()
    saved_data = State()
