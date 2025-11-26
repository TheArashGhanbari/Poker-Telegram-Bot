#!/usr/bin/env python3

import logging
import telebot
from pokerapp.entities import PlayerAction
from pokerapp.pokerbotmodel import PokerBotModel

logger = logging.getLogger(__name__)


class PokerBotCotroller:
    def __init__(self, model: PokerBotModel, bot: telebot.TeleBot):
        self._model = model
        self._bot = bot

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
                self._handle_start(message)
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
                self._model.middleware_user_turn_telebot(
                    self._handle_button_clicked,
                    call
                )
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
        if query_data == PlayerAction.CHECK.value:
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
