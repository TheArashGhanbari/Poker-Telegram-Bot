#!/usr/bin/env python3

import telebot
from pokerapp.entities import PlayerAction
from pokerapp.pokerbotmodel import PokerBotModel


class PokerBotCotroller:
    def __init__(self, model: PokerBotModel, bot: telebot.TeleBot):
        self._model = model
        self._bot = bot

        @bot.message_handler(commands=['ready'])
        def ready_handler(message):
            self._handle_ready(message)

        @bot.message_handler(commands=['start'])
        def start_handler(message):
            self._handle_start(message)

        @bot.message_handler(commands=['stop'])
        def stop_handler(message):
            self._handle_stop(message)

        @bot.message_handler(commands=['money'])
        def money_handler(message):
            self._handle_money(message)

        @bot.message_handler(commands=['ban'])
        def ban_handler(message):
            self._handle_ban(message)

        @bot.message_handler(commands=['cards'])
        def cards_handler(message):
            self._handle_cards(message)

        @bot.callback_query_handler(func=lambda call: True)
        def button_click_handler(call):
            self._model.middleware_user_turn_telebot(
                self._handle_button_clicked,
                call
            )

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
