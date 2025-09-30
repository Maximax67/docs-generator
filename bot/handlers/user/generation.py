import os
from typing import Dict, List, Optional, Tuple, Union
from aiogram.types import Message, CallbackQuery, FSInputFile, InaccessibleMessage
from aiogram.fsm.context import FSMContext

from app.settings import settings
from app.constants import DOC_COMPATIBLE_MIME_TYPES
from app.enums import VariableType
from app.models.database import Feedback, Result, PinnedFolder, User
from app.models.google import DriveFolder
from app.models.variables import MultichoiceVariable, PlainVariable
from app.services.documents import (
    generate_document,
    generate_preview,
    validate_document_variables,
)
from app.services.google_drive import (
    format_drive_file_metadata,
    format_drive_folder_metadata,
    get_accessible_folders,
    get_drive_item_metadata,
    get_folder_contents,
)

from app.services.variables import is_variable_value_valid, validate_variable
from app.utils import format_document_user_mention
from bot.keyboards.callback import GenerationCallback
from bot.keyboards.inline.document_preview import document_preview_keyboard
from bot.keyboards.inline.document_selector import document_selector_keyboard
from bot.keyboards.inline.multichoice_input import multichoice_input
from bot.keyboards.inline.suggest_save_data import suggest_save_data
from bot.keyboards.inline.text_input import text_input
from bot.states.generation import GenerationStates
from bot.utils.create_user import create_user
from bot.utils.delete_last_message import delete_last_message


async def initial_generation_handler(
    message: Message, state: FSMContext, user_id: int
) -> None:
    if not message.from_user:
        return

    await delete_last_message(message, state)
    await state.clear()

    user = await User.find_one(User.telegram_id == user_id)
    if not user:
        user = await create_user(message.from_user)

    if user.is_banned:
        await state.clear()
        await message.reply(
            "🚫 Ви заблоковані й не можете генерувати документи! "
            "За потреби зверніться до адміністраторів через зворотний зв'язок"
        )
        return

    folders = get_accessible_folders()
    pinned_folder_objs = await PinnedFolder.find_all().to_list()
    pinned_ids = {f.folder_id for f in pinned_folder_objs}
    pinned_folders: List[DriveFolder] = []

    for f in folders:
        if f["id"] in pinned_ids:
            folder = format_drive_folder_metadata(f)
            folder.is_pinned = True
            pinned_folders.append(folder)

    if not len(pinned_folders):
        await message.answer("Шаблони документів не завантажені в систему")
        return

    await state.set_state(GenerationStates.select_root_folder)

    answer = await message.answer(
        "Обери категорію документів:",
        reply_markup=document_selector_keyboard(pinned_folders, [], False),
    )

    await state.update_data(last_message_id=answer.message_id, selection_history=[])


async def generation_handler(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return

    await initial_generation_handler(message, state, message.from_user.id)


async def selection_menu(
    callback: CallbackQuery,
    state: FSMContext,
    folder_id: str,
    add_record: bool,
) -> None:
    if callback.message is None or isinstance(callback.message, InaccessibleMessage):
        raise Exception("Message is inaccessible")

    current_state = await state.get_state()
    if current_state != GenerationStates.selecting:
        await state.set_state(GenerationStates.selecting)

    current_folder_metadata = get_drive_item_metadata(folder_id)

    if current_folder_metadata["mimeType"] != "application/vnd.google-apps.folder":
        raise ValueError("Not a folder")

    contents = get_folder_contents(folder_id)

    pinned_folder_objs = await PinnedFolder.find_all().to_list()
    pinned_ids = {str(f.folder_id) for f in pinned_folder_objs}

    folders = []
    documents = []

    for item in contents:
        mime_type = item["mimeType"]

        if mime_type == "application/vnd.google-apps.folder":
            if item["id"] not in pinned_ids:
                folder = format_drive_file_metadata(item)
                folders.append(DriveFolder(**folder.model_dump(), is_pinned=False))
        elif mime_type in DOC_COMPATIBLE_MIME_TYPES:
            documents.append(format_drive_file_metadata(item))

    selection_history: List[Tuple[str, str]] = await state.get_value(
        "selection_history", []
    )

    if add_record:
        new_record = (folder_id, current_folder_metadata["name"])
        selection_history.append(new_record)

    names = [record[1] for record in selection_history]
    back_available = bool(selection_history) and len(selection_history) > 0

    if len(folders) or len(documents):
        text_to_send = "Категорія: " + " > ".join(names)
    else:
        text_to_send = "Категорія порожня: " + " > ".join(names)

    answer = await callback.message.answer(
        text_to_send,
        reply_markup=document_selector_keyboard(folders, documents, back_available),
    )

    await state.update_data(
        last_message_id=answer.message_id, selection_history=selection_history
    )


async def generation_folder_selected_handler(
    callback: CallbackQuery, callback_data: GenerationCallback, state: FSMContext
) -> None:
    if callback.message is None or isinstance(callback.message, InaccessibleMessage):
        raise Exception("Message is inaccessible")

    await delete_last_message(callback.message, state)

    folder_id = callback_data.q

    await selection_menu(callback, state, folder_id, True)


async def selecting_menu_back_handler(
    callback: CallbackQuery, state: FSMContext, from_preview: bool
) -> None:
    if callback.message is None or isinstance(callback.message, InaccessibleMessage):
        raise Exception("Message is inaccessible")

    selection_history: Optional[List[Tuple[str, str]]] = await state.get_value(
        "selection_history"
    )

    if not selection_history or (len(selection_history) <= 1 and not from_preview):
        await initial_generation_handler(callback.message, state, callback.from_user.id)
        return

    await delete_last_message(callback.message, state)

    if not from_preview:
        selection_history.pop()

    folder_id = selection_history[-1][0]

    await state.update_data(selection_history=selection_history)
    await selection_menu(callback, state, folder_id, False)


async def generation_folder_back_handler(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await selecting_menu_back_handler(callback, state, False)


async def preview_back_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await selecting_menu_back_handler(callback, state, True)


async def show_selected_document(
    callback: CallbackQuery, state: FSMContext, document_id: str
) -> None:
    if callback.message is None or isinstance(callback.message, InaccessibleMessage):
        raise Exception("Message is inaccessible")

    await delete_last_message(callback.message, state)

    processing_message = await callback.message.answer("⏳ Опрацьовую документ...")

    await state.update_data(
        last_message_id=processing_message.message_id,
    )

    await state.set_state(GenerationStates.document_preview)

    file_metadata = get_drive_item_metadata(document_id)
    file = format_drive_file_metadata(file_metadata)

    if file.mime_type not in DOC_COMPATIBLE_MIME_TYPES:
        raise ValueError("Invalid document mime type")

    if file.mime_type == "application/vnd.google-apps.document":
        filename = file.name
    else:
        filename, _ = os.path.splitext(file.name)

    pdf_file_path, template_variables = generate_preview(file)
    valid_variables, unknown_variables = validate_document_variables(template_variables)
    is_valid = len(unknown_variables) == 0

    required_variables: List[Union[PlainVariable, MultichoiceVariable]] = [
        var for var in valid_variables if var.type != VariableType.CONSTANT
    ]
    required_variables.sort(key=lambda v: v.name)

    required_variables_names: List[Tuple[str, str]] = [
        (var.variable, var.name) for var in required_variables
    ]

    user_id = callback.from_user.id

    user = await User.find_one(User.telegram_id == user_id)
    if not user:
        user = await create_user(callback.from_user)

    await delete_last_message(callback.message, state)

    try:
        user_filename = f"preview_{filename}" if required_variables_names else filename

        await callback.message.answer_document(
            FSInputFile(pdf_file_path, filename=f"{user_filename}.pdf")
        )

        if not required_variables_names:
            user_mention = format_document_user_mention(
                user.telegram_id, user.first_name, user.last_name, user.username
            )

            message = callback.message
            if message is None:
                raise Exception("Message is None")

            bot = message.bot
            if bot is None:
                raise Exception("Bot is None")

            admin_message = await bot.send_document(
                settings.ADMIN_CHAT_ID,
                FSInputFile(pdf_file_path, filename=f"{filename}.pdf"),
                message_thread_id=settings.ADMIN_DOCUMENTS_THREAD_ID,
                caption=f"Згенерував {user_mention}",
            )
    finally:
        os.remove(pdf_file_path)

    if not required_variables_names:
        context: Dict[str, str] = {}
        for var in valid_variables:
            if var.type == VariableType.MULTICHOICE:
                value = var.choices[0]
            elif var.type == VariableType.PLAIN:
                value = var.example or settings.DEFAULT_VARIABLE_VALUE
            else:
                value = var.value

            context[var.variable] = value

        await state.update_data(
            selected_document=document_id,
            context=context,
            user_id=user_id,
            admin_message_id=admin_message.message_id,
        )
        await generate_document_result(callback.message, state, True)
        return

    saved_variables = user.saved_variables

    numbered_lines: List[str] = []
    generate_now_available = True

    for i, (name, readable_name) in enumerate(required_variables_names, 1):
        saved_value = saved_variables.get(name)
        if saved_value and is_variable_value_valid(saved_value):
            variable = required_variables[i - 1]
            error = validate_variable(variable, saved_value)

            if error is None:
                numbered_lines.append(f"{i}. ⭐️ {readable_name}")
                continue

        generate_now_available = False
        numbered_lines.append(f"{i}. {readable_name}")

    numbered_variables = "\n".join(numbered_lines)
    notice = "" if is_valid else "\n\n⚠️ Документ можливо містить помилки в шаблоні"

    answer = await callback.message.answer(
        "Переглянь приклад заповненого документу, тобі потрібно буде ввести:\n"
        + numbered_variables
        + notice,
        reply_markup=document_preview_keyboard(generate_now_available),
    )

    await state.update_data(
        selected_document=document_id,
        last_message_id=answer.message_id,
        required_variables=required_variables,
        filled_data=[],
        saved_variables=saved_variables,
        user_id=user_id,
    )


async def generation_select_document_handler(
    callback: CallbackQuery, callback_data: GenerationCallback, state: FSMContext
) -> None:
    document_id = callback_data.q
    await show_selected_document(callback, state, document_id)


async def generate_now_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None or isinstance(callback.message, InaccessibleMessage):
        raise Exception("Message is inaccessible")

    filled_data: List[Optional[str]] = []
    required_variables: List[Union[PlainVariable, MultichoiceVariable]] = (
        await state.get_value("required_variables", [])
    )
    saved_variables: Dict[str, str] = await state.get_value("saved_variables", {})

    for var in required_variables:
        filled_data.append(saved_variables[var.variable])

    await state.update_data(filled_data=filled_data)
    await generate_document_result(callback.message, state, False)


async def ask_next_variable(message: Message, state: FSMContext) -> None:
    await delete_last_message(message, state)

    required_variables: List[Union[PlainVariable, MultichoiceVariable]] = (
        await state.get_value("required_variables", [])
    )
    filled_data: List[str] = await state.get_value("filled_data", [])
    saved_variables: Dict[str, str] = await state.get_value("saved_variables", {})

    position_to_fill = len(filled_data)
    if position_to_fill >= len(required_variables):
        await generate_document_result(message, state, False)
        return

    variable = required_variables[position_to_fill]
    saved_input = saved_variables.get(variable.variable)
    is_skippable = variable.allow_skip

    cur_state = await state.get_state()

    if variable.type == VariableType.MULTICHOICE:
        if cur_state != GenerationStates.filling_multichoise_variable:
            await state.set_state(GenerationStates.filling_multichoise_variable)

        answer_text = f'Оберіть значення для "{variable.name}":'
        keyboard = multichoice_input(variable.choices, saved_input, is_skippable)

    else:
        if cur_state != GenerationStates.filling_input_variable:
            await state.set_state(GenerationStates.filling_input_variable)

        if saved_input:
            error = validate_variable(variable, saved_input)
            if error:
                saved_input = None

        example = f".\n\nНаприклад: {variable.example}" if variable.example else ":"
        answer_text = f'Введіть значення для "{variable.name}"{example}'
        keyboard = text_input(saved_input, is_skippable)

    answer = await message.answer(answer_text, reply_markup=keyboard)

    await state.update_data(last_message_id=answer.message_id)


async def ask_next_variable_callback_handler(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if callback.message is None or isinstance(callback.message, InaccessibleMessage):
        raise Exception("Message is inaccessible")

    await ask_next_variable(callback.message, state)


async def answer_multichoice_handler(
    callback: CallbackQuery, callback_data: GenerationCallback, state: FSMContext
) -> None:
    required_variables: List[Union[PlainVariable, MultichoiceVariable]] = (
        await state.get_value("required_variables", [])
    )
    filled_data: List[str] = await state.get_value("filled_data", [])

    variable = required_variables[len(filled_data)]
    if not isinstance(variable, MultichoiceVariable):
        raise ValueError("Not a multichoice variable")

    selected = callback_data.q
    filled = "" if selected == "s" else variable.choices[int(selected)]

    filled_data.append(filled)

    await state.update_data(filled_data=filled_data)
    await ask_next_variable_callback_handler(callback, state)


async def use_offered_text_input_handler(
    callback: CallbackQuery, callback_data: GenerationCallback, state: FSMContext
) -> None:
    required_variables: List[Union[PlainVariable, MultichoiceVariable]] = (
        await state.get_value("required_variables", [])
    )
    filled_data: List[str] = await state.get_value("filled_data", [])

    variable = required_variables[len(filled_data)]

    if callback_data.q == "skip":
        filled = ""
    else:
        saved_variables: Dict[str, str] = await state.get_value("saved_variables", {})
        filled = saved_variables[variable.variable]

    filled_data.append(filled)

    await state.update_data(filled_data=filled_data)
    await ask_next_variable_callback_handler(callback, state)


async def answer_input_variable_handler(message: Message, state: FSMContext) -> None:
    required_variables: List[Union[PlainVariable, MultichoiceVariable]] = (
        await state.get_value("required_variables", [])
    )
    filled_data: List[str] = await state.get_value("filled_data", [])

    variable = required_variables[len(filled_data)]
    input_text = message.text or ""

    if is_variable_value_valid(input_text):
        error = validate_variable(variable, input_text)
    else:
        error = "Ти ввів занадто довгий текст"

    if error:
        if error.startswith("Invalid value for rule '"):
            await message.answer("Не валідне значення для цього поля! Повторіть ввід")
        else:
            await message.answer(error)
    else:
        filled_data.append(input_text)
        await state.update_data(filled_data=filled_data)

    await ask_next_variable(message, state)


async def return_to_previous_input_handler(
    callback: CallbackQuery, state: FSMContext
) -> None:
    filled_data: List[str] = await state.get_value("filled_data", [])

    if filled_data and len(filled_data) >= 1:
        filled_data.pop()
        await state.update_data(filled_data=filled_data)
        await ask_next_variable_callback_handler(callback, state)

        return

    document_id = await state.get_value("selected_document")
    if document_id is None:
        raise ValueError("Selected document is None")

    await show_selected_document(callback, state, document_id)


async def generate_document_result(
    message: Message, state: FSMContext, already_generated: bool
) -> None:
    await state.set_state(GenerationStates.results)

    user_id = await state.get_value("user_id")
    document_id = await state.get_value("selected_document")

    if document_id is None:
        raise ValueError("Selected document is None")

    save_data_option = 0  # Do not suggest to save

    user = await User.find_one(User.telegram_id == user_id)
    if user is None:
        raise ValueError("User not found")

    if already_generated:
        admin_message_id = await state.get_value("admin_message_id")
        context = await state.get_value("context")
    else:
        await delete_last_message(message, state)

        processing_message = await message.answer("⏳ Опрацьовую документ...")

        await state.update_data(
            last_message_id=processing_message.message_id,
        )

        required_variables: List[Union[PlainVariable, MultichoiceVariable]] = (
            await state.get_value("required_variables", [])
        )

        filled_data: List[str] = await state.get_value("filled_data", [])

        file_metadata = get_drive_item_metadata(document_id)
        file = format_drive_file_metadata(file_metadata)

        if file.mime_type not in DOC_COMPATIBLE_MIME_TYPES:
            raise ValueError("Invalid document mime type")

        saved_variables: Dict[str, str] = await state.get_value("saved_variables", {})

        variables: Dict[str, str] = {}
        for i, variable in enumerate(required_variables):
            value = filled_data[i]
            variables[variable.variable] = value

            if not value or not variable.allow_save:
                continue

            saved_value = saved_variables.get(variable.variable)
            if saved_value != value:
                save_data_option = 2  # Suggest update
            elif not saved_value and save_data_option == 0:
                save_data_option = 1  # Suggest save

        pdf_file_path, context = generate_document(file, variables)

        if file.mime_type == "application/vnd.google-apps.document":
            filename = file.name
        else:
            filename, _ = os.path.splitext(file.name)

        await delete_last_message(message, state)

        try:
            user_mention = format_document_user_mention(
                user.telegram_id, user.first_name, user.last_name, user.username
            )

            bot = message.bot
            if bot is None:
                raise Exception("Bot is None")

            admin_message = await bot.send_document(
                settings.ADMIN_CHAT_ID,
                FSInputFile(pdf_file_path, filename=f"{filename}.pdf"),
                message_thread_id=settings.ADMIN_DOCUMENTS_THREAD_ID,
                caption=f"Згенерував {user_mention}",
            )
            await message.answer_document(
                FSInputFile(pdf_file_path, filename=f"{filename}.pdf")
            )
        finally:
            os.remove(pdf_file_path)

        admin_message_id = admin_message.message_id

    await Result(
        user=user,
        template_id=document_id,
        variables=context,
        telegram_message_id=admin_message_id,
    ).insert()

    success_message = await message.answer(
        "Документ успішно згенеровано. "
        "Якщо сподобався бот, або маєш ідеї для покращення, надішли їх реплаєм на це повідомлення! "
        "Адміністратори його отримають",
    )

    if save_data_option == 0:
        await state.clear()
    else:
        if save_data_option == 1:
            suggest_text = "Бажаєш зберегти введені дані для більш швидкої генерації документів в майбутньому?"
        else:
            suggest_text = "Бажаєш оновити збережені дані?"

        answer = await message.answer(
            suggest_text,
            reply_markup=suggest_save_data(),
        )

        await state.update_data(last_message_id=answer.message_id)

    await Feedback(
        user_id=user_id,
        user_message_id=success_message.message_id,
        admin_message_id=admin_message_id,
    ).insert()


async def save_variables_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None or isinstance(callback.message, InaccessibleMessage):
        raise Exception("Message is inaccessible")

    await delete_last_message(callback.message, state)

    required_variables: List[Union[PlainVariable, MultichoiceVariable]] = (
        await state.get_value("required_variables", [])
    )
    filled_data: List[str] = await state.get_value("filled_data", [])

    user = await User.find_one(User.telegram_id == callback.from_user.id)
    if not user:
        user = await create_user(callback.from_user)

    for i, variable in enumerate(required_variables):
        filled_value = filled_data[i]
        if filled_value and variable.allow_save:
            user.saved_variables[variable.variable] = filled_value

    await user.save()
    await callback.message.answer("Дані успішно збережено")
    await state.clear()
