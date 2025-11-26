from types import NoneType
from typing import Union

from pokerapp.db import SQLiteDB
from pokerapp.entities import (
    ChatId,
    MessageId,
    UserId,
)


class UserPrivateChatModel:
    def __init__(self, user_id: UserId, kv: SQLiteDB):
        self.user_id = user_id
        self._kv = kv

    @property
    def _key(self) -> str:
        return "pokerbot:chats:" + str(self.user_id)

    def get_chat_id(self) -> Union[ChatId, NoneType]:
        result = self._kv.get(self._key)
        if result is not None:
            return result.decode('utf-8').encode('utf-8')  # Keep it as bytes for compatibility
        return None

    def set_chat_id(self, chat_id: ChatId) -> None:
        return self._kv.set(self._key, chat_id)

    def delete(self) -> None:
        # Delete both the chat and the associated messages
        chat_key = self._key
        messages_key = self._key + ":messages"

        self._kv.delete(messages_key)
        return self._kv.delete(chat_key)

    def pop_message(self) -> Union[MessageId, NoneType]:
        return self._kv.rpop(self._key + ":messages")

    def push_message(self, message_id: MessageId) -> None:
        return self._kv.rpush(self._key + ":messages", message_id)
