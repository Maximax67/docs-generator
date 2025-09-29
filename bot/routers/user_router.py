from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandStart, Command, StateFilter

from bot.handlers.common.close import close
from bot.handlers.user.exit_state import (
    exit_main_state_handler,
    exit_state_handler,
)
from bot.handlers.common.feedback import (
    feedback_handler,
    send_feedback_handler,
    user_feedback_reply_handler,
)
from bot.handlers.user.generation import (
    answer_input_variable_handler,
    answer_multichoice_handler,
    ask_next_variable_callback_handler,
    generate_now_handler,
    generation_folder_back_handler,
    generation_folder_selected_handler,
    generation_handler,
    generation_select_document_handler,
    preview_back_handler,
    return_to_previous_input_handler,
    save_variables_handler,
    use_offered_text_input_handler,
)
from bot.handlers.user.invalid_input import invalid_input_handler
from bot.handlers.user.saved_data import (
    delete_all_saved_handler,
    delete_saved_variable_handler,
    go_to_variable_handler,
    saved_data_handler,
    view_saved_variable_handler,
)
from bot.handlers.user.start import start_handler
from bot.handlers.user.statistics import statistics_handler
from bot.keyboards.inline.button import (
    GenerationCallback,
    MainCallback,
    SavedDataCallback,
)
from bot.states.feedback import FeedbackStates
from bot.states.generation import GenerationStates
from bot.states.saved_data import SavedDataStates


user_router = Router()
user_router.message.register(start_handler, CommandStart())

user_router.callback_query.register(close, MainCallback.filter(F.action == "close"))

user_router.callback_query.register(
    generation_folder_selected_handler,
    GenerationCallback.filter(F.action == "select_folder"),
)
user_router.callback_query.register(
    generation_folder_back_handler,
    GenerationCallback.filter(F.action == "back"),
    StateFilter(GenerationStates.selecting),
)
user_router.callback_query.register(
    preview_back_handler,
    GenerationCallback.filter(F.action == "back"),
    StateFilter(GenerationStates.document_preview),
)
user_router.callback_query.register(
    generation_select_document_handler,
    GenerationCallback.filter(F.action == "select_document"),
    StateFilter(GenerationStates.selecting),
)
user_router.callback_query.register(
    ask_next_variable_callback_handler,
    GenerationCallback.filter(F.action == "confirm_document"),
    StateFilter(GenerationStates.document_preview),
)
user_router.callback_query.register(
    generate_now_handler,
    GenerationCallback.filter(F.action == "generate_now"),
    StateFilter(GenerationStates.document_preview),
)
user_router.callback_query.register(
    return_to_previous_input_handler,
    GenerationCallback.filter(F.action == "back"),
    StateFilter(GenerationStates.filling_multichoise_variable),
)
user_router.callback_query.register(
    return_to_previous_input_handler,
    GenerationCallback.filter(F.action == "back"),
    StateFilter(GenerationStates.filling_input_variable),
)
user_router.callback_query.register(
    answer_multichoice_handler,
    GenerationCallback.filter(F.action == "answer_multichoice"),
    StateFilter(GenerationStates.filling_multichoise_variable),
)
user_router.callback_query.register(
    use_offered_text_input_handler,
    GenerationCallback.filter(F.action == "use_offered_text_input"),
    StateFilter(GenerationStates.filling_input_variable),
)
user_router.message.register(
    answer_input_variable_handler,
    StateFilter(GenerationStates.filling_input_variable),
    F.text,
)
user_router.callback_query.register(
    save_variables_handler,
    GenerationCallback.filter(F.action == "save_data"),
    StateFilter(GenerationStates.results),
)

user_router.callback_query.register(
    delete_all_saved_handler,
    SavedDataCallback.filter(F.action == "delete_all"),
    StateFilter(SavedDataStates.view_all),
)
user_router.callback_query.register(
    view_saved_variable_handler,
    SavedDataCallback.filter(F.action == "view"),
    StateFilter(SavedDataStates.view_all),
)
user_router.callback_query.register(
    delete_saved_variable_handler,
    SavedDataCallback.filter(F.action == "delete"),
    StateFilter(SavedDataStates.view_variable),
)
user_router.callback_query.register(
    go_to_variable_handler,
    SavedDataCallback.filter(F.action == "goto"),
    StateFilter(SavedDataStates),
)

user_router.message.register(generation_handler, Command("generate"))
user_router.message.register(feedback_handler, Command("feedback"))
user_router.message.register(statistics_handler, Command("statistics"))
user_router.message.register(saved_data_handler, Command("saved_data"))

user_router.message.register(
    generation_handler, F.text == "⚡ Генерація", F.chat.type == ChatType.PRIVATE
)
user_router.message.register(
    feedback_handler, F.text == "💬 Зворотний зв'язок", F.chat.type == ChatType.PRIVATE
)
user_router.message.register(
    statistics_handler, F.text == "📊 Статистика", F.chat.type == ChatType.PRIVATE
)
user_router.message.register(
    saved_data_handler, F.text == "💾 Збережені дані", F.chat.type == ChatType.PRIVATE
)

user_router.message.register(
    exit_state_handler,
    Command("cancel"),
    StateFilter(GenerationStates),
)
user_router.message.register(
    exit_state_handler, Command("cancel"), StateFilter(FeedbackStates)
)
user_router.message.register(
    exit_state_handler,
    Command("cancel"),
    StateFilter(SavedDataStates),
)

user_router.message.register(exit_main_state_handler, Command("cancel"))

user_router.message.register(
    send_feedback_handler, StateFilter(FeedbackStates.feedback)
)
user_router.message.register(user_feedback_reply_handler, F.reply_to_message)

user_router.message.register(invalid_input_handler, F.chat.type == ChatType.PRIVATE)
