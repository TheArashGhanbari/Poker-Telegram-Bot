#!/usr/bin/env python3

import datetime
import logging
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
        self._round_rate: RoundRateModel = RoundRateModel()

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
        game = self._get_or_create_game(str(message.chat.id))
        chat_id = str(message.chat.id)

        if game.state != GameState.INITIAL:
            self._view.send_message_reply(
                chat_id=chat_id,
                message_id=message.message_id,
                text="بازی شروع شده. صبر کنید!"
            )
            return

        if len(game.players) > MAX_PLAYERS:
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
                text="شما پول کافی ندارید",
            )

        game.ready_users.add(str(user.id))

        game.players.append(player)

        chat_members = self._bot.get_chat_members_count(chat_id)
        players_active = len(game.players)
        # One is the bot.
        if players_active == chat_members - 1 and \
                players_active >= self._min_players:
            self._start_game(game=game, chat_id=chat_id)

    def stop(self, user_id: UserId) -> None:
        UserPrivateChatModel(user_id=user_id, kv=self._kv).delete()

    def start(self, message: Message) -> None:
        game = self._get_or_create_game(str(message.chat.id))
        chat_id = str(message.chat.id)
        user_id = str(message.from_user.id)

        if game.state not in (GameState.INITIAL, GameState.FINISHED):
            self._view.send_message(
                chat_id=chat_id,
                text="بازی در حال انجام است"
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
                text="بازیکن کافی وجود ندارد"
            )
        return

    def _start_game(
        self,
        game: Game,
        chat_id: ChatId
    ) -> None:
        print(f"new game: {game.id}, players count: {len(game.players)}")

        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("poker")

        self._view.send_message(
            chat_id=chat_id,
            text='بازی شروع شد! 🃏',
            reply_markup=markup,
        )

        game.state = GameState.ROUND_PRE_FLOP
        self._divide_cards(game=game, chat_id=chat_id)

        game.current_player_index = 1
        self._round_rate.round_pre_flop_rate_before_first_turn(game)
        self._process_playing(chat_id=chat_id, game=game)
        self._round_rate.round_pre_flop_rate_after_first_turn(game)

    def bonus(self, message: Message) -> None:
        wallet = WalletManagerModel(
            str(message.from_user.id), self._kv)
        money = wallet.value()

        chat_id = str(message.chat.id)
        message_id = message.message_id

        if wallet.has_daily_bonus():
            return self._view.send_message_reply(
                chat_id=chat_id,
                message_id=message_id,
                text=f"پول شما: *{money}$*\n",
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
            self._view.send_message_reply(
                chat_id=chat_id,
                message_id=message_id,
                text=f"جایزه: *{bonus}$* {icon}\n" +
                f"پول شما: *{money}$*\n",
            )

        Timer(DICE_DELAY_SEC, print_bonus).start()

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
        chat_admins = self._bot.get_chat_administrators(chat_id)
        for m in chat_admins:
            if str(m.user.id) == user_id:
                return True
        return False

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
        text = "بازی با نتیجه زیر تمام شد:\n\n"
        for (player, best_hand, money) in winners_hand_money:
            win_hand = " ".join(best_hand)
            text += (
                f"{player.mention_markdown}:\n" +
                f"دریافت کرد: *{money} $*\n"
            )
            if not only_one_player:
                text += (
                    "با ترکیب کارت‌های:\n" +
                    f"{win_hand}\n\n"
                )
        text += "/ready برای ادامه"
        self._view.send_message(chat_id=chat_id, text=text)

        for player in game.players:
            player.wallet.approve(game.id)

        game.reset()

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
            self._view.send_message(
                chat_id=chat_id,
                text=f"{mention} {PlayerAction.ALL_IN.value} {amount}$"
            )
            player.state = PlayerState.ALL_IN
            self._process_playing(chat_id=chat_id, game=game)
        except Exception as e:
            logging.error(f"Error in all_in: {e}", exc_info=True)


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
