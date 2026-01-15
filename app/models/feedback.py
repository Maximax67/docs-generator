from beanie import Document


class Feedback(Document):
    user_id: int
    user_message_id: int
    admin_message_id: int

    class Settings:
        name = "feedback"
        indexes = [
            "admin_message_id",
            [("user_id", 1), ("user_message_id", 1)],
        ]
