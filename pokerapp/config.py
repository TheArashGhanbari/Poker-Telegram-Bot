import os


class Config:
    def __init__(self):
        self.DB_PATH: str = os.getenv(
            "POKERBOT_DB_PATH",
            default="pokerbot.db",
        )
        self.TOKEN: str = os.getenv(
            "POKERBOT_TOKEN",
            default="",
        )
        self.DEBUG: bool = bool(os.getenv(
            "POKERBOT_DEBUG",
            default="0"
        ) == "1")
