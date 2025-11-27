#!/usr/bin/env python3

import telebot
from telebot.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    InputMediaPhoto,
)
from io import BytesIO

from pokerapp.desk import DeskImageGenerator
from pokerapp.cards import Cards
from pokerapp.entities import (
    Game,
    Player,
    PlayerAction,
    MessageId,
    ChatId,
    Mention,
    Money,
)


class PokerBotViewer:
    def __init__(self, bot: telebot.TeleBot):
        self._bot = bot
        self._desk_generator = DeskImageGenerator()

    def send_message(
        self,
        chat_id: ChatId,
        text: str,
        reply_markup: ReplyKeyboardMarkup = None,
    ) -> None:
        # Use delayed method if available, otherwise use regular method
        if hasattr(self._bot, 'send_message_delayed'):
            self._bot.send_message_delayed(
                chat_id=chat_id,
                text=text,
                parse_mode='Markdown',
                reply_markup=reply_markup,
                disable_notification=True,
            )
        else:
            self._bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode='Markdown',
                reply_markup=reply_markup,
                disable_notification=True,
            )

    def send_photo(self, chat_id: ChatId) -> None:
        # TODO: photo to args.
        with open("./assets/poker_hand.jpg", 'rb') as photo:
            # Use delayed method if available, otherwise use regular method
            if hasattr(self._bot, 'send_photo_delayed'):
                self._bot.send_photo_delayed(
                    chat_id=chat_id,
                    photo=photo,
                    parse_mode='Markdown',
                    disable_notification=True,
                )
            else:
                self._bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    parse_mode='Markdown',
                    disable_notification=True,
                )

    def send_dice_reply(
        self,
        chat_id: ChatId,
        message_id: MessageId,
        emoji='🎲',
    ) -> Message:
        # Telebot does support send_dice - no need for delayed version for dice
        return self._bot.send_dice(
            chat_id=chat_id,
            emoji=emoji,
            reply_to_message_id=int(message_id),  # Convert message_id to int
            disable_notification=True,
        )

    def send_message_reply(
        self,
        chat_id: ChatId,
        message_id: MessageId,
        text: str,
    ) -> None:
        # Use delayed method if available, otherwise use regular method
        if hasattr(self._bot, 'send_message_delayed'):
            self._bot.send_message_delayed(
                chat_id=chat_id,
                text=text,
                parse_mode='Markdown',
                # Convert message_id to int
                reply_to_message_id=int(message_id),
                disable_notification=True,
            )
        else:
            self._bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode='Markdown',
                # Convert message_id to int
                reply_to_message_id=int(message_id),
                disable_notification=True,
            )

    def send_desk_cards_img(
        self,
        chat_id: ChatId,
        cards: Cards,
        caption: str = "",
        disable_notification: bool = True,
    ) -> int:
        im_cards = self._desk_generator.generate_desk(cards)
        bio = BytesIO()
        bio.name = 'desk.png'
        im_cards.save(bio, 'PNG')
        bio.seek(0)
        msg = self._bot.send_photo(
            chat_id=chat_id,
            photo=bio,
            caption=caption,
            disable_notification=disable_notification
        )
        return msg.message_id

    @staticmethod
    def _get_cards_markup(cards: Cards) -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup([cards], True, True)

    @staticmethod
    def _get_turns_markup(
        check_call_action: PlayerAction
    ) -> InlineKeyboardMarkup:
        keyboard = [[
            InlineKeyboardButton(
                text=PlayerAction.FOLD.value,
                callback_data=PlayerAction.FOLD.value,
            ),
            InlineKeyboardButton(
                text=PlayerAction.ALL_IN.value,
                callback_data=PlayerAction.ALL_IN.value,
            ),
            InlineKeyboardButton(
                text=check_call_action.value,
                callback_data=check_call_action.value,
            ),
        ], [
            InlineKeyboardButton(
                text=str(PlayerAction.SMALL.value) + "$",
                callback_data=str(PlayerAction.SMALL.value)
            ),
            InlineKeyboardButton(
                text=str(PlayerAction.NORMAL.value) + "$",
                callback_data=str(PlayerAction.NORMAL.value)
            ),
            InlineKeyboardButton(
                text=str(PlayerAction.BIG.value) + "$",
                callback_data=str(PlayerAction.BIG.value)
            ),
        ]]

        return InlineKeyboardMarkup(
            keyboard=keyboard  # In telebot, the parameter is 'keyboard', not 'inline_keyboard'
        )

    def send_cards(
            self,
            chat_id: ChatId,
            cards: Cards,
            mention_markdown: Mention,
            ready_message_id: str,
    ) -> None:
        markup = PokerBotViewer._get_cards_markup(cards)
        # Use delayed method if available, otherwise use regular method
        if hasattr(self._bot, 'send_message_delayed'):
            self._bot.send_message_delayed(
                chat_id=chat_id,
                text="نمایش کارت‌ها به " + mention_markdown,
                reply_markup=markup,
                reply_to_message_id=int(ready_message_id),
                parse_mode='Markdown',
                disable_notification=True,
            )
        else:
            self._bot.send_message(
                chat_id=chat_id,
                text="نمایش کارت‌ها به " + mention_markdown,
                reply_markup=markup,
                reply_to_message_id=int(ready_message_id),
                parse_mode='Markdown',
                disable_notification=True,
            )

    @staticmethod
    def define_check_call_action(
        game: Game,
        player: Player,
    ) -> PlayerAction:
        if player.round_rate == game.max_round_rate:
            return PlayerAction.CHECK
        return PlayerAction.CALL

    @staticmethod
    def _get_game_menu_markup(start_game_enabled: bool = False) -> InlineKeyboardMarkup:
        keyboard = []

        # Ready button
        keyboard.append([
            InlineKeyboardButton(
                text="✓ آماده",
                callback_data="ready"
            )
        ])

        # Start game button (only shown if there are enough players)
        if start_game_enabled:
            keyboard.append([
                InlineKeyboardButton(
                    text="▶ شروع بازی",
                    callback_data="start_game"
                )
            ])

        return InlineKeyboardMarkup(keyboard=keyboard)

    def send_turn_actions(
            self,
            chat_id: ChatId,
            game: Game,
            player: Player,
            money: Money,
    ) -> None:
        if len(game.cards_table) == 0:
            cards_table = "بدون کارت"
        else:
            cards_table = " ".join(game.cards_table)
        text = (
            "نوبت {}\n" +
            "{}\n" +
            "پول: *{}$*\n" +
            "حداکثر نرخ دور: *{}$*"
        ).format(
            player.mention_markdown,
            cards_table,
            money,
            game.max_round_rate,
        )
        check_call_action = PokerBotViewer.define_check_call_action(
            game, player
        )
        markup = PokerBotViewer._get_turns_markup(check_call_action)
        # Use delayed method if available, otherwise use regular method
        if hasattr(self._bot, 'send_message_delayed'):
            self._bot.send_message_delayed(
                chat_id=chat_id,
                text=text,
                reply_markup=markup,
                parse_mode='Markdown',
                disable_notification=True,
            )
        else:
            self._bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=markup,
                parse_mode='Markdown',
                disable_notification=True,
            )

    def remove_markup(
        self,
        chat_id: ChatId,
        message_id: MessageId,
    ) -> None:
        # Use delayed method if available, otherwise use regular method
        if hasattr(self._bot, 'edit_message_reply_markup_delayed'):
            self._bot.edit_message_reply_markup_delayed(
                chat_id=chat_id,
                message_id=int(message_id),
            )
        else:
            self._bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=int(message_id),
            )

    def remove_message(
        self,
        chat_id: ChatId,
        message_id: MessageId,
    ) -> None:
        # Use regular delete_message method (no delayed version needed for this)
        self._bot.delete_message(
            chat_id=chat_id,
            message_id=int(message_id),
        )
