#!/usr/bin/env python3

import logging
import telebot
from pokerapp.entities import PlayerAction
from pokerapp.pokerbotmodel import PokerBotModel
from pokerapp.privatechatmodel import UserPrivateChatModel
from pokerapp.db import SQLiteDB

DICES = "⚀⚁⚂⚃⚄⚅"
DESCRIPTION_FILE = "assets/description_bot.md"

logger = logging.getLogger(__name__)


class PokerBotCotroller:
    def __init__(self, model: PokerBotModel, bot: telebot.TeleBot):
        self._model = model
        self._bot = bot
        self._kv = model._kv  # Access the db from the model

        @bot.message_handler(commands=['ready'])
        def ready_handler(message):
            try:
                self._handle_ready(message)
            except Exception as e:
                logger.error(f"Error in ready_handler: {e}", exc_info=True)
                self._bot.send_message(
                    message.chat.id, "An error occurred while processing your ready command.")

        @bot.message_handler(commands=['start'])
        def start_handler(message):
            try:
                # Don't send game menu in private chat
                if message.chat.type == 'private':
                    # For private chat, just send the description as before
                    with open(DESCRIPTION_FILE, 'r', encoding='utf-8') as f:
                        text = f.read()

                    chat_id = str(message.chat.id)
                    user_id = str(message.from_user.id)
                    self._model._view.send_message(
                        chat_id=chat_id,
                        text=text,
                    )
                    self._model._view.send_photo(chat_id=chat_id)

                    # Save private chat ID
                    UserPrivateChatModel(user_id=user_id, kv=self._kv) \
                        .set_chat_id(chat_id=chat_id)
                    return

                # For group chats, check if the user is an admin to determine the behavior
                is_admin = self._model._check_access(str(message.chat.id), str(message.from_user.id))
                if is_admin:
                    # If admin, send the game menu
                    self._model.send_game_menu(message)
                else:
                    # If not admin, send the game menu (so players can see and click ready)
                    self._model.send_game_menu(message)
            except Exception as e:
                logger.error(f"Error in start_handler: {e}", exc_info=True)
                self._bot.send_message(
                    message.chat.id, "خطایی در پردازش دستور شروع رخ داد. لطفا دوباره امتحان کنید.")

        @bot.message_handler(commands=['stop'])
        def stop_handler(message):
            try:
                self._handle_stop(message)
            except Exception as e:
                logger.error(f"Error in stop_handler: {e}", exc_info=True)
                self._bot.send_message(
                    message.chat.id, "خطایی در پردازش دستور توقف رخ داد. لطفا دوباره امتحان کنید.")

        @bot.message_handler(commands=['money'])
        def money_handler(message):
            try:
                self._handle_money(message)
            except Exception as e:
                logger.error(f"Error in money_handler: {e}", exc_info=True)
                self._bot.send_message(
                    message.chat.id, "خطایی در پردازش دستور پول رخ داد. لطفا دوباره امتحان کنید.")

        @bot.message_handler(commands=['ban'])
        def ban_handler(message):
            try:
                self._handle_ban(message)
            except Exception as e:
                logger.error(f"Error in ban_handler: {e}", exc_info=True)
                self._bot.send_message(
                    message.chat.id, "خطایی در پردازش دستور محرومیت رخ داد. لطفا دوباره امتحان کنید.")

        @bot.message_handler(commands=['cards'])
        def cards_handler(message):
            try:
                self._handle_cards(message)
            except Exception as e:
                logger.error(f"Error in cards_handler: {e}", exc_info=True)
                self._bot.send_message(
                    message.chat.id, "خطایی در پردازش دستور کارت‌ها رخ داد. لطفا دوباره امتحان کنید.")

        @bot.callback_query_handler(func=lambda call: True)
        def button_click_handler(call):
            try:
                query_data = call.data
                # For game action buttons (CHECK, CALL, FOLD, RAISE, etc.), use middleware to check turns
                if query_data in [PlayerAction.CHECK.value, PlayerAction.CALL.value,
                                PlayerAction.FOLD.value, str(PlayerAction.SMALL.value),
                                str(PlayerAction.NORMAL.value), str(PlayerAction.BIG.value),
                                PlayerAction.ALL_IN.value]:
                    self._model.middleware_user_turn_telebot(
                        self._handle_button_clicked,
                        call
                    )
                else:
                    # For menu buttons (ready, start_game, show_players), handle directly
                    self._handle_button_clicked(call)
            except Exception as e:
                logger.error(
                    f"Error in button_click_handler: {e}", exc_info=True)
                if hasattr(call, 'message'):
                    self._bot.send_message(
                        call.message.chat.id, "An error occurred while processing your button click.")

    def _handle_ready(self, message) -> None:
        self._model.ready(message)

    def _handle_start(self, message) -> None:
        self._model.start(message)

    def _handle_stop(self, message) -> None:
        self._model.stop(user_id=message.from_user.id)

    def _handle_cards(self, message) -> None:
        self._model.send_cards_to_user(message)

    def _handle_ban(self, message) -> None:
        self._model.ban_player(message)

    def _handle_money(self, message) -> None:
        self._model.bonus(message)

    def _handle_button_clicked(self, call) -> None:
        query_data = call.data
        if query_data == "ready":
            self._model.handle_ready_button(call)
        elif query_data == "start_game":
            # Only allow admin to start the game
            is_admin = self._model._check_access(str(call.message.chat.id), str(call.from_user.id))
            if is_admin:
                self._model.start_game_from_menu(call)
            else:
                self._bot.answer_callback_query(
                    call.id,
                    text="فقط ادمین می‌تواند بازی را شروع کند"
                )
        elif query_data == "show_players":
            # This is just a display button, do nothing
            pass
        elif query_data == PlayerAction.CHECK.value:
            self._model.call_check(call)
        elif query_data == PlayerAction.CALL.value:
            self._model.call_check(call)
        elif query_data == PlayerAction.FOLD.value:
            self._model.fold(call)
        elif query_data == str(PlayerAction.SMALL.value):
            self._model.raise_rate_bet(call, PlayerAction.SMALL)
        elif query_data == str(PlayerAction.NORMAL.value):
            self._model.raise_rate_bet(call, PlayerAction.NORMAL)
        elif query_data == str(PlayerAction.BIG.value):
            self._model.raise_rate_bet(call, PlayerAction.BIG)
        elif query_data == PlayerAction.ALL_IN.value:
            self._model.all_in(call)
