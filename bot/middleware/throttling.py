import time
from typing import Any, Dict

from aiogram import BaseMiddleware
from aiogram.dispatcher.event.handler import HandlerObject

from bot.keyboards.inline.close_button import close_btn


class ThrottlingMiddleware(BaseMiddleware):
    """
    Middleware class to manage throttling of requests to prevent overloading.

    This middleware limits the rate of incoming requests from users. If a user exceeds the allowed
    request rate, they will receive a message indicating that they are making too many requests.
    """

    def __init__(self, default_rate: float = 0.5) -> None:
        """
        Initializes the ThrottlingMiddleware instance.

        Parameters:
        - default_rate (float): The initial rate limit in seconds (default is 0.5 seconds).

        This constructor sets up the initial rate limit and other throttling parameters.
        """
        self.limiters: Dict[Any, Any] = {}
        self.default_rate = default_rate
        self.count_throttled = 1
        self.last_throttled = 0

    async def __call__(self, handler: Any, event: Any, data: Dict[str, Any]) -> Any:
        """
        Processes incoming messages and enforces throttling rules.

        Parameters:
        - handler (HandlerObject): The handler to call if throttling rules are not violated.
        - event (types.Message): The incoming message or callback query.
        - data (dict): Additional data associated with the event.

        This method checks if the incoming request exceeds the allowed rate limit. If the rate limit
        is exceeded, the user will receive a message informing them of the throttling. If not, the
        handler is called to process the request.

        Returns:
        - None: The method does not return a value. It either processes the handler or sends a throttling message.
        """
        real_handler: HandlerObject = data["handler"]
        skip_pass = True

        if event.message:
            user_id = event.message.from_user.id
        elif event.callback_query:
            user_id = event.callback_query.from_user.id

        if real_handler.flags.get("skip_pass") is not None:
            skip_pass = real_handler.flags.get("skip_pass", False)

        if skip_pass:
            if int(time.time()) - self.last_throttled >= self.default_rate:
                self.last_throttled = int(time.time())
                self.default_rate = 0.5
                self.count_throttled = 0

                return await handler(event, data)
            else:
                if self.count_throttled >= 2:
                    self.default_rate = 3
                else:
                    self.count_throttled += 1
                    response = "Забагато запитів від тебе!"
                    try:
                        await event.callback_query.answer(response)
                    except Exception:
                        await event.bot.send_message(
                            chat_id=user_id, text=response, reply_markup=close_btn()
                        )

            self.last_throttled = int(time.time())
        else:
            return await handler(event, data)
