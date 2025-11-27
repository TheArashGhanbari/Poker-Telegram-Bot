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
from pokerapp.improved_entities import PlayerStats


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
                text="10$ 🟡",
                callback_data=str(PlayerAction.SMALL.value)
            ),
            InlineKeyboardButton(
                text="25$ 🟠",
                callback_data=str(PlayerAction.NORMAL.value)
            ),
            InlineKeyboardButton(
                text="50$ 🔴",
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
    def _get_game_menu_markup(start_game_enabled: bool = False, game_state: str = "initial") -> InlineKeyboardMarkup:
        keyboard = []

        # Different buttons based on game state
        if game_state == "initial" or game_state == "finished":
            # Ready button for joining game
            keyboard.append([
                InlineKeyboardButton(
                    text="✅ آماده",
                    callback_data="ready"
                )
            ])

            # Start game button (only shown if there are enough players and user is admin)
            if start_game_enabled:
                keyboard.append([
                    InlineKeyboardButton(
                        text="▶ شروع بازی",
                        callback_data="start_game"
                    )
                ])

            # Tournament option for admins
            keyboard.append([
                InlineKeyboardButton(
                    text="🏆 تورنمنت جدید",
                    callback_data="create_tournament"
                )
            ])
        else:
            # During game - show game status
            keyboard.append([
                InlineKeyboardButton(
                    text="ℹ️ وضعیت بازی",
                    callback_data="show_game_status"
                )
            ])

        # Additional menu options
        menu_row = []
        menu_row.append(InlineKeyboardButton(
            text="📊 امار",
            callback_data="show_stats"
        ))
        menu_row.append(InlineKeyboardButton(
            text="🏆 رده بندی",
            callback_data="show_leaderboard"
        ))
        menu_row.append(InlineKeyboardButton(
            text="💰 موجودی",
            callback_data="show_balance"
        ))
        keyboard.append(menu_row)

        return InlineKeyboardMarkup(keyboard=keyboard)

    def send_turn_actions(
            self,
            chat_id: ChatId,
            game: Game,
            player: Player,
            money: Money,
    ) -> None:
        if len(game.cards_table) == 0:
            cards_table = "🃏 کارت جامعه: هیچ کدام"
        else:
            cards_table = "🃏 کارت جامعه: " + " ".join(game.cards_table)

        # Calculate pot odds if applicable
        if game.max_round_rate > 0:
            call_amount = max(0, game.max_round_rate - player.round_rate)
            pot_odds_text = f" | 📊 شانس: {call_amount}:{game.pot-call_amount}" if (game.pot-call_amount) > 0 else ""
        else:
            pot_odds_text = ""

        # Create a more detailed status message
        text = (
            "🎮 نوبت: {}\n" +
            "{}\n" +
            "💰 موجودی: *{}$*\n" +
            "📈 حداکثر شرط دور: *{}$*{}"
        ).format(
            player.mention_markdown,
            cards_table,
            money,
            game.max_round_rate,
            pot_odds_text
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

    def send_game_results(
            self,
            chat_id: ChatId,
            winners_hand_money: list,
            only_one_player: bool,
            cards_table: Cards,
            pot: Money,
    ) -> None:
        """Send professional game results with detailed information"""
        text = "🎊 نتیجه بازی 🎊\n\n"

        for (player, best_hand, money) in winners_hand_money:
            win_hand = " ".join(best_hand)
            text += (
                f"🥇 {player.mention_markdown}:\n" +
                f"💰 دریافت کرد: *{money} $*\n"
            )
            if not only_one_player:
                text += (
                    "🃏 ترکیب برنده:\n" +
                    f"``` {win_hand} ```\n\n"
                )

        # Include final pot and table cards
        text += f"팟 نهایی: *{pot}$*\n"
        if cards_table:
            text += f"کارت‌های جامعه: {' '.join(cards_table)}\n"

        # Use delayed method if available, otherwise use regular method
        if hasattr(self._bot, 'send_message_delayed'):
            self._bot.send_message_delayed(
                chat_id=chat_id,
                text=text,
                parse_mode='Markdown',
                disable_notification=False,  # Enable notification for game results
            )
        else:
            self._bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode='Markdown',
                disable_notification=False,  # Enable notification for game results
            )

    def send_player_stats(
            self,
            chat_id: ChatId,
            player_stats,  # PlayerStats type - imported dynamically to avoid circular dependency
    ) -> None:
        """Send player statistics"""
        text = (
            f"📊 اطلاعات بازیکن:\n\n"
            f"🎮 بازی‌های انجام شده: {player_stats.total_games_played}\n"
            f"🏆 بازی‌های برنده: {player_stats.total_games_won}\n"
            f"📈 درصد برد: {player_stats.total_games_won * 100.0 / max(1, player_stats.total_games_played):.1f}%\n"
            f"💸 سود کل: {player_stats.total_money_earned - player_stats.total_money_spent}$\n"
            f"💰 سود خالص: {player_stats.total_money_earned}$\n"
            f"🔥 رشته برنده: {player_stats.current_winning_streak}\n"
            f"🏆 بهترین رشته: {player_stats.best_winning_streak}\n"
            f"⏰ زمان بازی: {player_stats.total_time_played}\n"
        )

        if player_stats.best_hand_won:
            text += f"🎯 بهترین دست: {player_stats.best_hand_won}\n"

        # Use delayed method if available, otherwise use regular method
        if hasattr(self._bot, 'send_message_delayed'):
            self._bot.send_message_delayed(
                chat_id=chat_id,
                text=text,
                parse_mode='Markdown',
                disable_notification=True,
            )
        else:
            self._bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode='Markdown',
                disable_notification=True,
            )

    def send_leaderboard(
            self,
            chat_id: ChatId,
            top_players: list,
    ) -> None:
        """Send top players leaderboard"""
        text = "🏆 رده بندی برترین بازیکنان:\n\n"

        for i, player in enumerate(top_players, 1):
            user_id = player['user_id']
            total_games_won = player['total_games_won']
            win_rate = player['win_rate']
            text += f"{i}. {user_id} | 🏆 {total_games_won} | 📊 {win_rate:.1f}%\n"

        # Use delayed method if available, otherwise use regular method
        if hasattr(self._bot, 'send_message_delayed'):
            self._bot.send_message_delayed(
                chat_id=chat_id,
                text=text,
                parse_mode='Markdown',
                disable_notification=True,
            )
        else:
            self._bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode='Markdown',
                disable_notification=True,
            )
