#!/usr/bin/env python3

import datetime
import logging
import re
import traceback
from threading import Timer
from typing import List, Tuple, Dict

import telebot
from telebot.types import Message, ReplyKeyboardMarkup, InlineKeyboardMarkup

from pokerapp.config import Config
from pokerapp.privatechatmodel import UserPrivateChatModel
from pokerapp.winnerdetermination import WinnerDetermination
from pokerapp.cards import Cards
from pokerapp.db import SQLiteDB
from pokerapp.entities import (
    Game,
    GameState,
    Player,
    ChatId,
    UserId,
    UserException,
    Money,
    PlayerAction,
    PlayerState,
    Score,
    Wallet,
)
from pokerapp.improved_entities import (
    PlayerStats,
    GameType
)
from pokerapp.gamestatsmodel import GameStatsModel
from pokerapp.tournamentmanager import TournamentManager
from pokerapp.pokerbotview import PokerBotViewer


DICE_MULT = 10
DICE_DELAY_SEC = 5
BONUSES = (5, 20, 40, 80, 160, 320)
DICES = "⚀⚁⚂⚃⚄⚅"

MAX_PLAYERS = 8
MIN_PLAYERS = 2
SMALL_BLIND = 5
ONE_DAY = 86400
DEFAULT_MONEY = 1000
MAX_TIME_FOR_TURN = datetime.timedelta(minutes=2)
DESCRIPTION_FILE = "assets/description_bot.md"

# Storage for games, using chat_id as key
chat_games = {}


class PokerBotModel:
    def __init__(
        self,
        view: PokerBotViewer,
        bot: telebot.TeleBot,
        cfg: Config,
        kv: SQLiteDB,
    ):
        self._view: PokerBotViewer = view
        self._bot: telebot.TeleBot = bot
        self._winner_determine: WinnerDetermination = WinnerDetermination()
        self._kv: SQLiteDB = kv
        self._cfg: Config = cfg
        self._stats_model: GameStatsModel = GameStatsModel(cfg.DB_PATH)
        self._round_rate: RoundRateModel = RoundRateModel(
            kv=self._kv, stats_model=self._stats_model)
        self._tournament_manager: TournamentManager = TournamentManager()

        self._readyMessages = {}

    @property
    def _min_players(self):
        if self._cfg.DEBUG:
            return 1

        return MIN_PLAYERS

    @staticmethod
    def _get_or_create_game(chat_id: str) -> Game:
        if chat_id not in chat_games:
            chat_games[chat_id] = Game()
        return chat_games[chat_id]

    @staticmethod
    def _current_turn_player(game: Game) -> Player:
        i = game.current_player_index % len(game.players)
        return game.players[i]

    def ready(self, message: Message) -> None:
        try:
            game = self._get_or_create_game(str(message.chat.id))
            chat_id = str(message.chat.id)

            if game.state != GameState.INITIAL:
                self._view.send_message_reply(
                    chat_id=chat_id,
                    message_id=message.message_id,
                    text="بازی شروع شده. صبر کنید!"
                )
                return

            if len(game.players) >= MAX_PLAYERS:  # Use >= instead of >
                self._view.send_message_reply(
                    chat_id=chat_id,
                    text="اتاق پر است",
                    message_id=message.message_id,
                )
                return

            user = message.from_user

            # Check if user has started private chat with bot
            user_chat_model = UserPrivateChatModel(
                user_id=str(user.id),
                kv=self._kv,
            )
            private_chat_id = user_chat_model.get_chat_id()
            if private_chat_id is None:
                self._view.send_message_reply(
                    chat_id=chat_id,
                    message_id=message.message_id,
                    text="لطفا ابتدا ربات را در چت خصوصی خود استارت کنید تا کارت‌های شما به صورت خصوصی ارسال شود. سپس دوباره /ready را امتحان کنید.",
                )
                return

            if user.id in game.ready_users:
                self._view.send_message_reply(
                    chat_id=chat_id,
                    message_id=message.message_id,
                    text="شما قبلا آماده هستید",
                )
                return

            player = Player(
                user_id=str(user.id),
                mention_markdown=f"[{user.first_name}](tg://user?id={user.id})",
                wallet=WalletManagerModel(str(user.id), self._kv),
                ready_message_id=str(message.message_id),
            )

            if player.wallet.value() < 2*SMALL_BLIND:
                return self._view.send_message_reply(
                    chat_id=chat_id,
                    message_id=message.message_id,
                    text=f"💰 شما پول کافی ندارید (حداقل {SMALL_BLIND*2}$)",
                )

            game.ready_users.add(str(user.id))
            game.players.append(player)

            chat_members = self._bot.get_chat_members_count(chat_id)
            players_active = len(game.players)
            # One is the bot.
            if players_active >= self._min_players and players_active == chat_members - 1:
                self._start_game(game=game, chat_id=chat_id)
        except Exception as e:
            logging.error(f"Error in ready: {e}", exc_info=True)
            chat_id = str(message.chat.id)
            self._view.send_message(
                chat_id=chat_id,
                text="❌ خطایی در پردازش دستور آماده رخ داد. لطفا دوباره امتحان کنید."
            )

    def stop(self, user_id: UserId) -> None:
        UserPrivateChatModel(user_id=user_id, kv=self._kv).delete()

    def start(self, message: Message) -> None:
        try:
            game = self._get_or_create_game(str(message.chat.id))
            chat_id = str(message.chat.id)
            user_id = str(message.from_user.id)

            if game.state not in (GameState.INITIAL, GameState.FINISHED):
                self._view.send_message(
                    chat_id=chat_id,
                    text="🎮 بازی در حال انجام است"
                )
                return

            # One is the bot.
            chat_members = self._bot.get_chat_members_count(chat_id) - 1
            if chat_members == 1:
                with open(DESCRIPTION_FILE, 'r', encoding='utf-8') as f:
                    text = f.read()

                chat_id = str(message.chat.id)
                self._view.send_message(
                    chat_id=chat_id,
                    text=text,
                )
                self._view.send_photo(chat_id=chat_id)

                if message.chat.type == 'private':
                    UserPrivateChatModel(user_id=user_id, kv=self._kv) \
                        .set_chat_id(chat_id=chat_id)

                return

            players_active = len(game.players)
            if players_active >= self._min_players:
                self._start_game(game=game, chat_id=chat_id)
            else:
                self._view.send_message(
                    chat_id=chat_id,
                    text="👥 بازیکن کافی وجود ندارد"
                )
        except Exception as e:
            logging.error(f"Error in start: {e}", exc_info=True)
            chat_id = str(message.chat.id)
            self._view.send_message(
                chat_id=chat_id,
                text="❌ خطایی در پردازش دستور شروع رخ داد. لطفا دوباره امتحان کنید."
            )

    def _start_game(
        self,
        game: Game,
        chat_id: ChatId
    ) -> None:
        print(f"new game: {game.id}, players count: {len(game.players)}")

        self._view.send_message(
            chat_id=chat_id,
            text='بازی شروع شد! 🃏',
        )

        game.state = GameState.ROUND_PRE_FLOP
        self._divide_cards(game=game, chat_id=chat_id)

        game.current_player_index = 1
        self._round_rate.round_pre_flop_rate_before_first_turn(game)
        self._process_playing(chat_id=chat_id, game=game)
        self._round_rate.round_pre_flop_rate_after_first_turn(game)

    def bonus(self, message: Message) -> None:
        try:
            wallet = WalletManagerModel(
                str(message.from_user.id), self._kv)
            money = wallet.value()

            chat_id = str(message.chat.id)
            message_id = message.message_id

            if wallet.has_daily_bonus():
                return self._view.send_message_reply(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"شما امروز قبلاً جایزه را دریافت کرده‌اید\n💰 موجودی: *{money}$*",
                )

            icon: str
            dice_msg: Message
            bonus: Money

            SATURDAY = 5
            if datetime.datetime.today().weekday() == SATURDAY:
                dice_msg = self._view.send_dice_reply(
                    chat_id=chat_id,
                    message_id=message_id,
                    emoji='🎰'
                )
                icon = '🎰'
                bonus = dice_msg.dice.value * 20
            else:
                dice_msg = self._view.send_dice_reply(
                    chat_id=chat_id,
                    message_id=message_id,
                )
                icon = DICES[dice_msg.dice.value-1]
                bonus = BONUSES[dice_msg.dice.value - 1]

            message_id = dice_msg.message_id
            money = wallet.add_daily(amount=bonus)

            def print_bonus() -> None:
                try:
                    self._view.send_message_reply(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"🎉 جایزه: *{bonus}$* {icon}\n" +
                        f"💰 موجودی: *{money}$*",
                    )
                except Exception as e:
                    logging.error(f"Error in print_bonus: {e}", exc_info=True)

            Timer(DICE_DELAY_SEC, print_bonus).start()
        except Exception as e:
            logging.error(f"Error in bonus: {e}", exc_info=True)
            chat_id = str(message.chat.id)
            self._view.send_message(
                chat_id=chat_id,
                text="❌ خطایی در دریافت جایزه رخ داد. لطفا دوباره امتحان کنید."
            )

    def send_cards_to_user(
        self,
        message: Message,
    ) -> None:
        game = self._get_or_create_game(str(message.chat.id))
        user_id = str(message.from_user.id)

        current_player = None
        for player in game.players:
            if player.user_id == user_id:
                current_player = player
                break

        if current_player is None or not current_player.cards:
            return

        self._view.send_cards(
            chat_id=str(message.chat.id),
            cards=current_player.cards,
            mention_markdown=current_player.mention_markdown,
            ready_message_id=str(message.message_id),
        )

    def _check_access(self, chat_id: ChatId, user_id: UserId) -> bool:
        # Get chat information to determine chat type
        try:
            chat = self._bot.get_chat(chat_id)
            # In private chats, the concept of administrators doesn't apply, so return false
            if chat.type == 'private':
                return False
        except:
            # If there's an issue getting chat info, assume it's not private
            pass

        try:
            chat_admins = self._bot.get_chat_administrators(chat_id)
            for m in chat_admins:
                if str(m.user.id) == user_id:
                    return True
        except:
            # If we can't get admins (e.g., in private chat), return False
            return False
        return False

    def send_game_menu(self, message: Message) -> None:
        """Send game menu with inline buttons to the chat"""
        game = self._get_or_create_game(str(message.chat.id))
        chat_id = str(message.chat.id)
        user_id = str(message.from_user.id)

        # Check if the user is an admin
        is_admin = self._check_access(chat_id, user_id)

        # Build players list as text with bullet points
        players_list_text = ""
        if game.players:
            # Sort players alphabetically by name
            sorted_players = sorted(game.players, key=lambda p: re.search(r'\[([^\]]+)\]', p.mention_markdown).group(
                1).lower() if re.search(r'\[([^\]]+)\]', p.mention_markdown) else p.mention_markdown.lower())

            players_list_text = f"✓ بازیکنان ({len(game.players)}):\n"
            for player in sorted_players:
                # Extract just the name from the mention markdown
                # Extract name from markdown mention [name](tg://user?id=1234)
                name_match = re.search(
                    r'\[([^\]]+)\]', player.mention_markdown)
                player_name = name_match.group(
                    1) if name_match else player.mention_markdown
                players_list_text += f"• {player_name}\n"
        else:
            players_list_text = "✓ هیچ بازیکنی آماده نیست\n"

        # Determine if start game button should be enabled
        start_game_enabled = is_admin and len(
            game.players) >= self._min_players

        # Create markup without players list (players shown in message text)
        game_state_str = game.state.value if hasattr(
            game.state, 'value') else 'initial'
        markup = self._view._get_game_menu_markup(
            start_game_enabled, game_state_str)

        # Send the game menu message with player list
        sent_message = self._bot.send_message(
            chat_id=chat_id,
            text=f"منوی بازی پوکر:\n{players_list_text}",
            reply_markup=markup,
            parse_mode='Markdown'
        )

        # Save the message ID so we can update it later
        game.menu_message_id = str(sent_message.message_id)

    def handle_ready_button(self, call) -> None:
        """Handle the ready button press from inline keyboard"""
        chat_id = str(call.message.chat.id)
        game = self._get_or_create_game(chat_id)
        user = call.from_user

        if game.state != GameState.INITIAL:
            self._bot.answer_callback_query(
                call.id,
                text="بازی شروع شده. صبر کنید!"
            )
            return

        if len(game.players) >= MAX_PLAYERS:
            self._bot.answer_callback_query(
                call.id,
                text="اتاق پر است"
            )
            return

        # Check if user has started private chat with bot
        user_chat_model = UserPrivateChatModel(
            user_id=str(user.id),
            kv=self._kv,
        )
        private_chat_id = user_chat_model.get_chat_id()
        if private_chat_id is None:
            self._bot.answer_callback_query(
                call.id,
                text="لطفا ابتدا ربات را در چت خصوصی خود استارت کنید"
            )
            return

        # Check both in ready_users and in players list to prevent duplicates
        if user.id in game.ready_users:
            self._bot.answer_callback_query(
                call.id,
                text="شما قبلا آماده هستید"
            )
            return

        # Additional check: see if player already exists in players list
        for player in game.players:
            if player.user_id == str(user.id):
                self._bot.answer_callback_query(
                    call.id,
                    text="شما قبلا آماده هستید"
                )
                return

        player = Player(
            user_id=str(user.id),
            mention_markdown=f"[{user.first_name}](tg://user?id={user.id})",
            wallet=WalletManagerModel(str(user.id), self._kv),
            ready_message_id=str(call.message.message_id),
        )

        if player.wallet.value() < 2*SMALL_BLIND:
            self._bot.answer_callback_query(
                call.id,
                text="شما پول کافی ندارید"
            )
            return

        game.ready_users.add(str(user.id))
        game.players.append(player)

        # Refresh the game menu to show updated player list (without sending extra message)
        self.refresh_game_menu(chat_id, call.message.message_id)

        # Note: Game will NOT start automatically - admin must press start_game button

    def refresh_game_menu(self, chat_id: str, original_message_id: str = None) -> None:
        """Refresh the game menu to show updated player list"""
        game = self._get_or_create_game(chat_id)

        # Only refresh if we have a stored menu message ID
        if game.menu_message_id is None:
            return

        # Build players list as text with bullet points
        players_list_text = ""
        if game.players:
            # Sort players alphabetically by name
            sorted_players = sorted(game.players, key=lambda p: re.search(r'\[([^\]]+)\]', p.mention_markdown).group(
                1).lower() if re.search(r'\[([^\]]+)\]', p.mention_markdown) else p.mention_markdown.lower())

            players_list_text = f"✓ بازیکنان ({len(game.players)}):\n"
            for player in sorted_players:
                # Extract just the name from the mention markdown
                # Extract name from markdown mention [name](tg://user?id=1234)
                name_match = re.search(
                    r'\[([^\]]+)\]', player.mention_markdown)
                player_name = name_match.group(
                    1) if name_match else player.mention_markdown
                players_list_text += f"• {player_name}\n"
        else:
            players_list_text = "✓ هیچ بازیکنی آماده نیست\n"

        # Determine if start game button should be enabled (check if there are enough players and an admin is present)
        # Since we don't have user context for admin check, we'll just check if there are enough players
        # The admin check will happen when the button is pressed
        start_game_enabled = len(game.players) >= self._min_players

        # Create markup without players list (players shown in message text)
        game_state_str = game.state.value if hasattr(
            game.state, 'value') else 'initial'
        markup = self._view._get_game_menu_markup(
            start_game_enabled, game_state_str)

        # Edit the existing message
        try:
            self._bot.edit_message_text(
                chat_id=chat_id,
                message_id=int(game.menu_message_id),
                text=f"منوی بازی پوکر:\n{players_list_text}",
                reply_markup=markup,
                parse_mode='Markdown'
            )
        except Exception as e:
            # If the message can't be edited (e.g. was deleted), send a new one
            print(f"Error editing menu message: {e}")
            # Send a new menu message
            self.send_game_menu_for_refresh(chat_id)

    def send_game_menu_for_refresh(self, chat_id: str) -> None:
        """Send a new game menu when the original can't be refreshed"""
        game = self._get_or_create_game(chat_id)

        # Build players list as text with bullet points
        players_list_text = ""
        if game.players:
            # Sort players alphabetically by name
            sorted_players = sorted(game.players, key=lambda p: re.search(r'\[([^\]]+)\]', p.mention_markdown).group(
                1).lower() if re.search(r'\[([^\]]+)\]', p.mention_markdown) else p.mention_markdown.lower())

            players_list_text = f"✓ بازیکنان ({len(game.players)}):\n"
            for player in sorted_players:
                # Extract just the name from the mention markdown
                # Extract name from markdown mention [name](tg://user?id=1234)
                name_match = re.search(
                    r'\[([^\]]+)\]', player.mention_markdown)
                player_name = name_match.group(
                    1) if name_match else player.mention_markdown
                players_list_text += f"• {player_name}\n"
        else:
            players_list_text = "✓ هیچ بازیکنی آماده نیست\n"

        # Determine if start game button should be enabled (check if there are enough players)
        start_game_enabled = len(game.players) >= self._min_players

        # Create markup without players list (players shown in message text)
        game_state_str = game.state.value if hasattr(
            game.state, 'value') else 'initial'
        markup = self._view._get_game_menu_markup(
            start_game_enabled, game_state_str)

        # Send the game menu message
        sent_message = self._bot.send_message(
            chat_id=chat_id,
            text=f"منوی بازی پوکر:\n{players_list_text}",
            reply_markup=markup,
            parse_mode='Markdown'
        )

        # Update the stored message ID
        game.menu_message_id = str(sent_message.message_id)

    def start_game_from_menu(self, call) -> None:
        """Start the game from the menu button"""
        game = self._get_or_create_game(str(call.message.chat.id))
        chat_id = str(call.message.chat.id)

        if game.state not in (GameState.INITIAL, GameState.FINISHED):
            self._bot.answer_callback_query(
                call.id,
                text="بازی در حال انجام است"
            )
            return

        players_active = len(game.players)
        if players_active >= self._min_players:
            # Start the game
            self._start_game(game=game, chat_id=chat_id)
            self._bot.answer_callback_query(
                call.id,
                text="بازی شروع شد!"
            )
        else:
            self._bot.answer_callback_query(
                call.id,
                text="بازیکن کافی وجود ندارد"
            )

    def _send_cards_private(self, player: Player, cards: Cards) -> None:
        try:
            user_chat_model = UserPrivateChatModel(
                user_id=player.user_id,
                kv=self._kv,
            )
            private_chat_id = user_chat_model.get_chat_id()

            if private_chat_id is None:
                logging.warning(
                    f"Private chat not found for user {player.user_id}")
                return  # Instead of raising, just return to avoid crashing

            private_chat_id = private_chat_id.decode('utf-8')

            message_id = str(self._view.send_desk_cards_img(
                chat_id=private_chat_id,
                cards=cards,
                caption="کارت‌های شما",
                disable_notification=False,
            ))

            try:
                rm_msg_id = user_chat_model.pop_message()
                while rm_msg_id is not None:
                    try:
                        rm_msg_id = rm_msg_id.decode('utf-8')
                        self._view.remove_message(
                            chat_id=private_chat_id,
                            message_id=rm_msg_id,
                        )
                    except Exception as ex:
                        logging.error(
                            f"remove_message error: {ex}", exc_info=True)
                    rm_msg_id = user_chat_model.pop_message()

                user_chat_model.push_message(message_id=message_id)
            except Exception as ex:
                logging.error(
                    f"bulk_remove_message error: {ex}", exc_info=True)
        except Exception as e:
            logging.error(f"Error in _send_cards_private: {e}", exc_info=True)

    def _divide_cards(self, game: Game, chat_id: ChatId) -> None:
        for player in game.players:
            cards = player.cards = [
                game.remain_cards.pop(),
                game.remain_cards.pop(),
            ]

            try:
                self._send_cards_private(player=player, cards=cards)

                continue
            except Exception as ex:
                print(ex)
                pass

            self._view.send_cards(
                chat_id=chat_id,
                cards=cards,
                mention_markdown=player.mention_markdown,
                ready_message_id=player.ready_message_id,
            )

    def _process_playing(self, chat_id: ChatId, game: Game) -> None:
        game.current_player_index += 1
        game.current_player_index %= len(game.players)

        current_player = self._current_turn_player(game)

        # Process next round.
        if current_player.user_id == game.trading_end_user_id:
            self._round_rate.to_pot(game)
            self._goto_next_round(game, chat_id)

            game.current_player_index = 0

        # Game finished.
        if game.state == GameState.INITIAL:
            return

        # Player could be changed.
        current_player = self._current_turn_player(game)

        current_player_money = current_player.wallet.value()

        # Player do not have monery so make it ALL_IN.
        if current_player_money <= 0:
            current_player.state = PlayerState.ALL_IN

        # Skip inactive players.
        if current_player.state != PlayerState.ACTIVE:
            self._process_playing(chat_id, game)
            return

        # All fold except one.
        all_in_active_players = game.players_by(
            states=(PlayerState.ACTIVE, PlayerState.ALL_IN)
        )
        if len(all_in_active_players) == 1:
            self._finish(game, chat_id)
            return

        game.last_turn_time = datetime.datetime.now()
        self._view.send_turn_actions(
            chat_id=chat_id,
            game=game,
            player=current_player,
            money=current_player_money,
        )

    def add_cards_to_table(
        self,
        count: int,
        game: Game,
        chat_id: ChatId,
    ) -> None:
        for _ in range(count):
            game.cards_table.append(game.remain_cards.pop())

        self._view.send_desk_cards_img(
            chat_id=chat_id,
            cards=game.cards_table,
            caption=f"پات فعلی: {game.pot}$",
        )

    def _finish(
        self,
        game: Game,
        chat_id: ChatId,
    ) -> None:
        self._round_rate.to_pot(game)

        print(
            f"game finished: {game.id}, " +
            f"players count: {len(game.players)}, " +
            f"pot: {game.pot}"
        )

        active_players = game.players_by(
            states=(PlayerState.ACTIVE, PlayerState.ALL_IN)
        )

        player_scores = self._winner_determine.determinate_scores(
            players=active_players,
            cards_table=game.cards_table,
        )

        winners_hand_money = self._round_rate.finish_rate(
            game=game,
            player_scores=player_scores,
        )

        only_one_player = len(active_players) == 1

        # Send professional game results
        self._view.send_game_results(
            chat_id=chat_id,
            winners_hand_money=winners_hand_money,
            only_one_player=only_one_player,
            cards_table=game.cards_table,
            pot=game.pot
        )

        # Update player statistics
        for player in game.players:
            # Increment games played for all players
            self._stats_model.increment_stat(
                player.user_id, 'total_games_played', 1)

            # For winners, update win statistics
            for (winner_player, best_hand, money) in winners_hand_money:
                if player.user_id == winner_player.user_id:
                    self._stats_model.increment_stat(
                        player.user_id, 'total_games_won', 1)
                    self._stats_model.increment_stat(
                        player.user_id, 'total_money_earned', money)

                    # Record the best hand won
                    hand_type = self._get_hand_type_description(best_hand)
                    self._stats_model.update_best_hand(
                        player.user_id, hand_type)
                else:
                    # For losers, reset winning streak
                    self._stats_model.reset_winning_streak(player.user_id)

        # Record game in history
        end_time = datetime.datetime.now()
        winner_user_ids = [winner[0].user_id for winner in winners_hand_money]
        winner_id = winner_user_ids[0] if winner_user_ids else None

        self._stats_model.record_game(
            game_id=game.id,
            chat_id=chat_id,
            start_time=game.created_at,
            end_time=end_time,
            winner_user_id=winner_id,
            pot_amount=game.pot,
            players_count=len(game.players),
            game_type=game.game_type.value
        )

        # Reset the game but preserve the menu message ID so we can update the menu
        old_menu_message_id = game.menu_message_id
        # Keep a copy of the old players to calculate who won
        old_players = game.players[:]
        game.reset()
        # Restore the menu message ID for the new game state
        game.menu_message_id = old_menu_message_id

        # Refresh the game menu to show the current state (no players yet for new game)
        try:
            self.refresh_game_menu(chat_id)
        except:
            # If refreshing fails, send a new menu
            try:
                self.send_game_menu_for_refresh(chat_id)
            except:
                # If everything fails, at least the game is reset
                pass

    def _get_hand_type_description(self, best_hand) -> str:
        """Convert best hand to a human-readable description"""
        # This needs to be implemented based on the winner determination logic
        # For now, we'll return a basic description based on hand evaluation
        hand_values = [card.value for card in best_hand]
        hand_suits = [card.suit for card in best_hand]

        # Simple heuristics for hand type (this could be improved with the full winner determination logic)
        if len(set(hand_suits)) == 1:
            if set(hand_values) == {10, 11, 12, 13, 14}:
                return "Royal Flush"
            elif len(set([v - hand_values[i-1] for i, v in enumerate(hand_values[1:])])) == 1:
                return "Straight Flush"
            else:
                return "Flush"
        elif len(set(hand_values)) == 2:
            # Either four of a kind or full house
            value_counts = {}
            for v in hand_values:
                value_counts[v] = value_counts.get(v, 0) + 1
            if 4 in value_counts.values():
                return "Four of a Kind"
            else:
                return "Full House"
        elif len(set([v - hand_values[i-1] for i, v in enumerate(hand_values[1:])])) == 1:
            return "Straight"
        elif 3 in [hand_values.count(v) for v in set(hand_values)]:
            return "Three of a Kind"
        elif 2 in [hand_values.count(v) for v in set(hand_values)]:
            pair_count = len([v for v in set(hand_values)
                             if hand_values.count(v) == 2])
            if pair_count == 2:
                return "Two Pair"
            else:
                return "Pair"
        else:
            return "High Card"

    def _goto_next_round(self, game: Game, chat_id: ChatId) -> bool:
        # The state of the last player becomes ALL_IN at end of the round .
        active_players = game.players_by(
            states=(PlayerState.ACTIVE,)
        )
        if len(active_players) == 1:
            active_players[0].state = PlayerState.ALL_IN
            if len(game.cards_table) == 5:
                self._finish(game, chat_id)
                return

        def add_cards(cards_count):
            return self.add_cards_to_table(
                count=cards_count,
                game=game,
                chat_id=chat_id
            )

        state_transitions = {
            GameState.ROUND_PRE_FLOP: {
                "next_state": GameState.ROUND_FLOP,
                "processor": lambda: add_cards(3),
            },
            GameState.ROUND_FLOP: {
                "next_state": GameState.ROUND_TURN,
                "processor": lambda: add_cards(1),
            },
            GameState.ROUND_TURN: {
                "next_state": GameState.ROUND_RIVER,
                "processor": lambda: add_cards(1),
            },
            GameState.ROUND_RIVER: {
                "next_state": GameState.FINISHED,
                "processor": lambda: self._finish(game, chat_id),
            }
        }

        if game.state not in state_transitions:
            raise Exception("unexpected state: " + game.state.value)

        transation = state_transitions[game.state]
        game.state = transation["next_state"]
        transation["processor"]()

    def middleware_user_turn_telebot(self, fn, call) -> None:
        chat_id = str(call.message.chat.id)
        game = self._get_or_create_game(chat_id)

        if game.state == GameState.INITIAL:
            return

        current_player = self._current_turn_player(game)
        current_user_id = str(call.from_user.id)
        if current_user_id != current_player.user_id:
            return

        fn(call)
        self._view.remove_markup(
            chat_id=chat_id,
            message_id=call.message.message_id,
        )

    def ban_player(self, message: Message) -> None:
        chat_id = str(message.chat.id)
        game = self._get_or_create_game(chat_id)

        if game.state in (GameState.INITIAL, GameState.FINISHED):
            return

        diff = datetime.datetime.now() - game.last_turn_time
        if diff < MAX_TIME_FOR_TURN:
            self._view.send_message(
                chat_id=chat_id,
                text="نمی‌توانید محرومیت اعمال کنید. حداکثر زمان نوبت ۲ دقیقه است",
            )
            return

        self._view.send_message(
            chat_id=chat_id,
            text="زمان تمام شد!",
        )
        self.fold(message)

    def fold(self, call) -> None:
        # This method is called with a callback query
        try:
            if hasattr(call, 'message'):
                chat_id = str(call.message.chat.id)
                game = self._get_or_create_game(chat_id)
                player = self._current_turn_player(game)

                player.state = PlayerState.FOLD

                # Update player statistics
                self._stats_model.increment_stat(
                    player.user_id, 'total_folded', 1)

                self._view.send_message(
                    chat_id=chat_id,
                    text=f"{player.mention_markdown} {PlayerAction.FOLD.value}"
                )

                self._process_playing(
                    chat_id=chat_id,
                    game=game,
                )
            else:
                logging.error(
                    "fold called with invalid call object: no message attribute")
        except Exception as e:
            logging.error(f"Error in fold: {e}", exc_info=True)

    def call_check(self, call) -> None:
        # This method is called with a callback query
        try:
            if not hasattr(call, 'message'):
                logging.error(
                    "call_check called with invalid call object: no message attribute")
                return
            chat_id = str(call.message.chat.id)
            game = self._get_or_create_game(chat_id)
            player = self._current_turn_player(game)

            action = PlayerAction.CALL.value
            if player.round_rate == game.max_round_rate:
                action = PlayerAction.CHECK.value
                # Update check statistics
                self._stats_model.increment_stat(
                    player.user_id, 'total_checked', 1)
            else:
                # Update call statistics
                self._stats_model.increment_stat(
                    player.user_id, 'total_called', 1)

            try:
                amount = game.max_round_rate - player.round_rate
                if player.wallet.value() <= amount:
                    return self.all_in(call)

                mention_markdown = self._current_turn_player(
                    game).mention_markdown
                self._view.send_message(
                    chat_id=chat_id,
                    text=f"{mention_markdown} {action}"
                )

                self._round_rate.call_check(game, player)
            except UserException as e:
                self._view.send_message(chat_id=chat_id, text=str(e))
                return

            self._process_playing(
                chat_id=chat_id,
                game=game,
            )
        except Exception as e:
            logging.error(f"Error in call_check: {e}", exc_info=True)

    def raise_rate_bet(
        self,
        call,
        raise_bet_rate: PlayerAction
    ) -> None:
        chat_id = str(call.message.chat.id)
        game = self._get_or_create_game(chat_id)
        player = self._current_turn_player(game)

        try:
            action = PlayerAction.RAISE_RATE
            if player.round_rate == game.max_round_rate:
                action = PlayerAction.BET

            if player.wallet.value() < raise_bet_rate.value:
                return self.all_in(call)

            # Update raise statistics
            self._stats_model.increment_stat(player.user_id, 'total_raised', 1)

            self._view.send_message(
                chat_id=chat_id,
                text=player.mention_markdown +
                f" {action.value} {raise_bet_rate.value}$"
            )

            self._round_rate.raise_rate_bet(game, player, raise_bet_rate.value)
        except UserException as e:
            self._view.send_message(chat_id=chat_id, text=str(e))
            return

        self._process_playing(chat_id=chat_id, game=game)

    def all_in(self, call) -> None:
        try:
            if not hasattr(call, 'message'):
                logging.error(
                    "all_in called with invalid call object: no message attribute")
                return
            chat_id = str(call.message.chat.id)
            game = self._get_or_create_game(chat_id)
            player = self._current_turn_player(game)
            mention = player.mention_markdown
            amount = self._round_rate.all_in(game, player)

            # Update player statistics (we can consider all-in as a type of raise)
            self._stats_model.increment_stat(player.user_id, 'total_raised', 1)

            self._view.send_message(
                chat_id=chat_id,
                text=f"{mention} {PlayerAction.ALL_IN.value} {amount}$"
            )
            player.state = PlayerState.ALL_IN
            self._process_playing(chat_id=chat_id, game=game)
        except Exception as e:
            logging.error(f"Error in all_in: {e}", exc_info=True)

    def show_balance(self, call) -> None:
        """Show the balance of the user who clicked the button"""
        try:
            user_id = str(call.from_user.id)
            chat_id = str(call.message.chat.id)

            # Get the user's wallet
            wallet = WalletManagerModel(user_id, self._kv)
            balance = wallet.value()

            # Send balance info in a user-friendly way
            self._bot.answer_callback_query(
                call.id,
                text=f"💰 موجودی شما: {balance}$",
                show_alert=False
            )
        except Exception as e:
            logging.error(f"Error in show_balance: {e}", exc_info=True)
            # Send error message silently
            self._bot.answer_callback_query(
                call.id,
                text="❌ خطا در دریافت موجودی",
                show_alert=False
            )

    def show_leaderboard(self, call) -> None:
        """Show the top players based on their win statistics"""
        try:
            chat_id = str(call.message.chat.id)

            # Get top players from the stats model
            top_players = self._stats_model.get_top_players(limit=5)

            if not top_players:
                self._bot.answer_callback_query(
                    call.id,
                    text="هیچ بازیکنی در لیدربرد وجود ندارد",
                    show_alert=False
                )
                return

            # Format the leaderboard text
            leaderboard_text = "🏆 لیدربرد:\n"
            for i, player in enumerate(top_players, 1):
                user_id = player['user_id']
                wins = player['total_games_won']
                total_games = player['total_games_played']
                win_rate = player['win_rate']

                # Get the user's name using the bot API
                try:
                    user = self._bot.get_chat_member(chat_id, user_id).user
                    username = user.first_name
                except:
                    # If we can't get the user info, just show user_id
                    username = f"Player {user_id}"

                leaderboard_text += f"{i}. {username}: {wins} برد / {total_games} بازی ({win_rate:.1f}%)\n"

            self._bot.answer_callback_query(
                call.id,
                text=leaderboard_text,
                show_alert=False
            )
        except Exception as e:
            logging.error(f"Error in show_leaderboard: {e}", exc_info=True)
            self._bot.answer_callback_query(
                call.id,
                text="❌ خطا در دریافت لیدربرد",
                show_alert=False
            )

    def show_player_stats(self, call) -> None:
        """Show the statistics of the user who clicked the button"""
        try:
            user_id = str(call.from_user.id)
            chat_id = str(call.message.chat.id)

            # Get the user's stats
            stats = self._stats_model.get_player_stats(user_id)

            # Format the stats text
            stats_text = f"📊 آمار بازیکن:\n"
            stats_text += f"• تعداد بازی‌ها: {stats.total_games_played}\n"
            stats_text += f"• تعداد برد: {stats.total_games_won}\n"
            stats_text += f"• تعداد باخت: {stats.total_games_played - stats.total_games_won}\n"
            stats_text += f"• میزان پول کسب شده: {stats.total_money_earned}$\n"
            stats_text += f"• تعداد فولد: {stats.total_folded}\n"
            stats_text += f"• تعداد ریز: {stats.total_raised}\n"
            stats_text += f"• تعداد چک: {stats.total_checked}\n"
            stats_text += f"• تعداد کال: {stats.total_called}\n"

            if stats.best_hand_won:
                stats_text += f"• بهترین دست برنده: {stats.best_hand_won}\n"

            if stats.current_winning_streak > 0:
                stats_text += f"• رشته برد فعلی: {stats.current_winning_streak}\n"

            # Calculate win rate
            if stats.total_games_played > 0:
                win_rate = (stats.total_games_won / stats.total_games_played) * 100
                stats_text += f"• درصد برد: {win_rate:.1f}%\n"

            self._bot.answer_callback_query(
                call.id,
                text=stats_text,
                show_alert=False
            )
        except Exception as e:
            logging.error(f"Error in show_player_stats: {e}", exc_info=True)
            self._bot.answer_callback_query(
                call.id,
                text="❌ خطا در دریافت آمار بازیکن",
                show_alert=False
            )


class WalletManagerModel(Wallet):
    def __init__(self, user_id: UserId, kv: SQLiteDB):
        self.user_id = user_id
        self._kv = kv

        key = self._prefix(self.user_id)
        if self._kv.get(key) is None:
            self._kv.set(key, DEFAULT_MONEY)

    @staticmethod
    def _prefix(id: str, suffix: str = ""):
        return "pokerbot:" + str(id) + suffix

    def _current_date(self) -> str:
        return datetime.datetime.utcnow().strftime("%d/%m/%y")

    def _key_daily(self) -> str:
        return self._prefix(self.user_id, ":daily")

    def has_daily_bonus(self) -> bool:
        current_date = self._current_date()
        last_date = self._kv.get(self._key_daily())

        return last_date is not None and \
            last_date.decode("utf-8") == current_date

    def add_daily(self, amount: Money) -> Money:
        if self.has_daily_bonus():
            raise UserException(
                "You have already received the bonus today\n"
                f"Your money: {self.value()}$"
            )

        key = self._prefix(self.user_id)
        self._kv.set(self._key_daily(), self._current_date())

        return self._kv.incrby(key, amount)

    def inc(self, amount: Money = 0) -> None:
        """ افزایش تعداد پول در کیف پول.
            کاهش پول مجاز.
        """
        wallet = int(self._kv.get(self._prefix(self.user_id)).decode('utf-8'))

        if wallet + amount < 0:
            raise UserException("پول کافی ندارید")

        self._kv.incrby(self._prefix(self.user_id), amount)

    def inc_authorized_money(
        self,
        game_id: str,
        amount: Money
    ) -> None:
        # Use the new method in SQLiteDB for authorized money
        current_amount = self._kv.get_authorized_money(self.user_id, game_id)
        new_amount = current_amount + amount
        self._kv.set_authorized_money(self.user_id, game_id, new_amount)

    def authorized_money(self, game_id: str) -> Money:
        # Use the new method in SQLiteDB for authorized money
        return self._kv.get_authorized_money(self.user_id, game_id)

    def authorize(self, game_id: str, amount: Money) -> None:
        """ کاهش تعداد پول. """
        self.inc_authorized_money(game_id, amount)

        return self.inc(-amount)

    def authorize_all(self, game_id: str) -> Money:
        """ کاهش تمام پول بازیکن. """
        wallet = int(self._kv.get(self._prefix(self.user_id)).decode('utf-8'))
        self.inc_authorized_money(game_id, wallet)

        self._kv.set(self._prefix(self.user_id), 0)
        return wallet

    def value(self) -> Money:
        """ Get count of money in the wallet. """
        result = self._kv.get(self._prefix(self.user_id))
        if result is None:
            return DEFAULT_MONEY
        return int(result.decode('utf-8'))

    def approve(self, game_id: str) -> None:
        # Use the new method in SQLiteDB for authorized money
        self._kv.delete_authorized_money(self.user_id, game_id)


class RoundRateModel:
    def __init__(self, kv: SQLiteDB, stats_model: GameStatsModel):
        self._kv = kv
        self._stats_model = stats_model

    def round_pre_flop_rate_before_first_turn(self, game: Game) -> None:
        self.raise_rate_bet(game, game.players[0], SMALL_BLIND)
        self.raise_rate_bet(game, game.players[1], SMALL_BLIND)

    def round_pre_flop_rate_after_first_turn(self, game: Game) -> None:
        dealer = 2 % len(game.players)
        game.trading_end_user_id = game.players[dealer].user_id

    def raise_rate_bet(self, game: Game, player: Player, amount: int) -> None:
        amount += game.max_round_rate - player.round_rate

        player.wallet.authorize(
            game_id=game.id,
            amount=amount,
        )
        player.round_rate += amount

        game.max_round_rate = player.round_rate
        game.trading_end_user_id = player.user_id

    def call_check(self, game, player) -> None:
        amount = game.max_round_rate - player.round_rate

        player.wallet.authorize(
            game_id=game.id,
            amount=amount,
        )
        player.round_rate += amount

    def all_in(self, game, player) -> Money:
        amount = player.wallet.authorize_all(
            game_id=game.id,
        )
        player.round_rate += amount
        if game.max_round_rate < player.round_rate:
            game.max_round_rate = player.round_rate
            game.trading_end_user_id = player.user_id
        return amount

    def _sum_authorized_money(
        self,
        game: Game,
        players: List[Tuple[Player, Cards]],
    ) -> int:
        sum_authorized_money = 0
        for player in players:
            sum_authorized_money += player[0].wallet.authorized_money(
                game_id=game.id,
            )
        return sum_authorized_money

    def finish_rate(
        self,
        game: Game,
        player_scores: Dict[Score, List[Tuple[Player, Cards]]],
    ) -> List[Tuple[Player, Cards, Money]]:
        sorted_player_scores_items = sorted(
            player_scores.items(),
            reverse=True,
            key=lambda x: x[0],
        )
        player_scores_values = list(
            map(lambda x: x[1], sorted_player_scores_items))

        res = []
        for win_players in player_scores_values:
            players_authorized = self._sum_authorized_money(
                game=game,
                players=win_players,
            )
            if players_authorized <= 0:
                continue

            game_pot = game.pot
            for win_player, best_hand in win_players:
                if game.pot <= 0:
                    break

                authorized = win_player.wallet.authorized_money(
                    game_id=game.id,
                )

                win_money_real = game_pot * (authorized / players_authorized)
                win_money_real = round(win_money_real)

                win_money_can_get = authorized * len(game.players)
                win_money = min(win_money_real, win_money_can_get)

                win_player.wallet.inc(win_money)
                game.pot -= win_money
                res.append((win_player, best_hand, win_money))

        return res

    def to_pot(self, game) -> None:
        for p in game.players:
            game.pot += p.round_rate
            p.round_rate = 0
        game.max_round_rate = 0
        game.trading_end_user_id = game.players[0].user_id
