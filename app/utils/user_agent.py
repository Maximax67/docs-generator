from fastapi import Request
from user_agents import parse  # type: ignore[import-untyped]


def get_session_name_from_user_agent(request: Request) -> str:
    user_agent_str = request.headers.get("user-agent", "")
    user_agent = parse(user_agent_str)

    return str(user_agent).replace(" / ", ", ")
