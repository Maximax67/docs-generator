from typing import Dict, List, Optional, Tuple
from aiogram.types import Message, CallbackQuery, InaccessibleMessage
from aiogram.fsm.context import FSMContext
from pymongo import ReturnDocument

from app.enums import VariableType
from app.models.database import User
from app.services.config import get_variables_dict
from bot.keyboards.callback import SavedDataCallback
from bot.keyboards.inline.saved_variables import saved_variables_keyboard
from bot.keyboards.inline.view_variable import view_variable_keyboard
from bot.states.saved_data import SavedDataStates
from bot.utils.create_user import create_user
from bot.utils.delete_last_message import delete_last_message


async def variables_selector(
    message: Message,
    state: FSMContext,
    saved_valid_variables: List[Tuple[str, str]],
    pos: int,
) -> None:
    if not saved_valid_variables:
        await message.answer("Збережені дані відсутні")
        await state.clear()
        return

    cur_state = await state.get_state()
    if cur_state != SavedDataStates.view_all:
        await state.set_state(SavedDataStates.view_all)

    answer = await message.answer(
        "Твої збережені дані:",
        reply_markup=saved_variables_keyboard(saved_valid_variables, pos),
    )

    await state.update_data(last_message_id=answer.message_id)


async def saved_data_handler(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    await delete_last_message(message, state)
    await state.clear()

    user = await User.find_one(User.telegram_id == message.from_user.id)
    if not user:
        user = await create_user(message.from_user)

    saved_variables = user.saved_variables

    if not saved_variables:
        await message.answer("Збережені дані відсутні")
        return

    available_variables = get_variables_dict()

    saved_valid_variables: List[Tuple[str, str]] = [
        (var.variable, var.name)
        for var in available_variables.values()
        if var.type != VariableType.CONSTANT
        and var.allow_save
        and var.variable in saved_variables
    ]

    await state.set_data(
        {
            "saved_valid_variables": saved_valid_variables,
            "saved_variables": saved_variables,
        }
    )

    await variables_selector(message, state, saved_valid_variables, 0)


async def delete_all_saved_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None or isinstance(callback.message, InaccessibleMessage):
        raise Exception("Message is inaccessible")

    await delete_last_message(callback.message, state)
    await state.clear()

    user_id = callback.from_user.id
    updated_user: Optional[
        User
    ] = await User.get_pymongo_collection().find_one_and_update(
        {"telegram_id": user_id},
        {"$set": {"saved_variables": {}}},
        return_document=ReturnDocument.AFTER,
    )

    if not updated_user:
        raise Exception("User not found")

    answer = await callback.message.answer("Усі дані успішно видалено")

    await state.set_data(
        {
            "last_message_id": answer.message_id,
        }
    )


async def view_saved_variable_handler(
    callback: CallbackQuery, callback_data: SavedDataCallback, state: FSMContext
) -> None:
    if callback.message is None or isinstance(callback.message, InaccessibleMessage):
        raise Exception("Message is inaccessible")

    await delete_last_message(callback.message, state)
    await state.set_state(SavedDataStates.view_variable)

    selected_pos = int(callback_data.q)

    saved_valid_variables: List[Tuple[str, str]] = await state.get_value(
        "saved_valid_variables", []
    )
    saved_variables: Dict[str, str] = await state.get_value("saved_variables", {})

    name, readable_name = saved_valid_variables[selected_pos]
    variable_value = saved_variables[name]

    answer = await callback.message.answer(
        f'Збережене значення для "{readable_name}":\n\n{variable_value}',
        reply_markup=view_variable_keyboard(selected_pos),
    )

    await state.update_data(last_message_id=answer.message_id)


async def delete_saved_variable_handler(
    callback: CallbackQuery, callback_data: SavedDataCallback, state: FSMContext
) -> None:
    if callback.message is None or isinstance(callback.message, InaccessibleMessage):
        raise Exception("Message is inaccessible")

    await delete_last_message(callback.message, state)

    selected_pos = int(callback_data.q)

    saved_valid_variables: List[Tuple[str, str]] = await state.get_value(
        "saved_valid_variables", []
    )
    saved_variables: Dict[str, str] = await state.get_value("saved_variables", {})

    name, readable_name = saved_valid_variables.pop(selected_pos)
    del saved_variables[name]

    updated_user: Optional[
        User
    ] = await User.get_pymongo_collection().find_one_and_update(
        {"telegram_id": callback.from_user.id},
        {"$unset": {f"saved_variables.{name}": ""}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated_user:
        raise Exception("User not found")

    await state.update_data(
        saved_variables=saved_variables, saved_valid_variables=saved_valid_variables
    )

    await callback.message.answer(f'Значення для "{readable_name}" видалено')

    if selected_pos == len(saved_valid_variables):
        selected_pos -= 1

    await variables_selector(
        callback.message, state, saved_valid_variables, selected_pos
    )


async def go_to_variable_handler(
    callback: CallbackQuery, callback_data: SavedDataCallback, state: FSMContext
) -> None:
    if callback.message is None or isinstance(callback.message, InaccessibleMessage):
        raise Exception("Message is inaccessible")

    await delete_last_message(callback.message, state)

    selected_pos = int(callback_data.q)
    saved_valid_variables: List[Tuple[str, str]] = await state.get_value(
        "saved_valid_variables", []
    )

    await variables_selector(
        callback.message, state, saved_valid_variables, selected_pos
    )
