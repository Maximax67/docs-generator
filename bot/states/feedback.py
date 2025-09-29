from aiogram.fsm.state import State, StatesGroup


class FeedbackStates(StatesGroup):
    feedback = State()
