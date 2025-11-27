#!/usr/bin/env python3

from abc import abstractmethod
import enum
import datetime
from typing import Tuple, List, Dict, Optional
from uuid import uuid4
from pokerapp.cards import get_cards


MessageId = str
ChatId = str
UserId = str
Mention = str
Score = int
Money = int
GameId = str


@abstractmethod
class Wallet:
    @staticmethod
    def _prefix(id: int, suffix: str = ""):
        pass

    def add_daily(self) -> Money:
        pass

    def inc(self, amount: Money = 0) -> None:
        pass

    def inc_authorized_money(self, game_id: str, amount: Money) -> None:
        pass

    def authorized_money(self, game_id: str) -> Money:
        pass

    def authorize(self, game_id: str, amount: Money) -> None:
        pass

    def authorize_all(self, game_id: str) -> Money:
        pass

    def value(self) -> Money:
        pass

    def approve(self, game_id: str) -> None:
        pass


class Player:
    def __init__(
        self,
        user_id: UserId,
        mention_markdown: Mention,
        wallet: Wallet,
        ready_message_id: str,
    ):
        self.user_id = user_id
        self.mention_markdown = mention_markdown
        self.state = PlayerState.ACTIVE
        self.wallet = wallet
        self.cards = []
        self.round_rate = 0
        self.ready_message_id = ready_message_id
        self.total_won = 0  # Track total amount won by this player
        self.total_played = 0  # Track total amount played by this player
        self.last_action_time = datetime.datetime.now()  # Track when player last took action

    def __repr__(self):
        return "{}({!r})".format(self.__class__.__name__, self.__dict__)


class PlayerState(enum.Enum):
    ACTIVE = 1
    FOLD = 0
    ALL_IN = 10


class GameType(enum.Enum):
    TEXAS_HOLDEM = "Texas Hold'em"
    NO_LIMIT_TEXAS_HOLDEM = "No Limit Texas Hold'em"
    POT_LIMIT_TEXAS_HOLDEM = "Pot Limit Texas Hold'em"


class Game:
    def __init__(self, game_type: GameType = GameType.TEXAS_HOLDEM):
        # Initialize menu_message_id before calling reset
        self.menu_message_id = None
        self.game_type = game_type
        self.reset()

    def reset(self):
        # Preserve the menu message ID so we can update the game menu after game ends
        old_menu_message_id = self.menu_message_id
        self.id = str(uuid4())
        self.pot = 0
        self.max_round_rate = 0
        self.state = GameState.INITIAL
        self.players: List[Player] = []
        self.cards_table = []
        self.current_player_index = -1
        self.remain_cards = get_cards()
        self.trading_end_user_id = 0
        self.ready_users = set()
        self.last_turn_time = datetime.datetime.now()
        self.menu_message_id = old_menu_message_id  # Preserve the menu message ID for updates
        self.small_blind_amount = 5  # Default small blind
        self.big_blind_amount = 10  # Default big blind
        self.min_raise_amount = 10  # Minimum raise amount
        self.max_players = 8  # Maximum players in a game
        self.created_at = datetime.datetime.now()
        self.start_time: Optional[datetime.datetime] = None
        self.end_time: Optional[datetime.datetime] = None

    def players_by(self, states: Tuple[PlayerState]) -> List[Player]:
        return list(filter(lambda p: p.state in states, self.players))

    def active_players(self) -> List[Player]:
        return self.players_by((PlayerState.ACTIVE, PlayerState.ALL_IN))

    def all_alive_players(self) -> List[Player]:
        return self.players_by((PlayerState.ACTIVE,))

    def set_blinds(self, small_blind: int, big_blind: int):
        self.small_blind_amount = small_blind
        self.big_blind_amount = big_blind

    def __repr__(self):
        return "{}({!r})".format(self.__class__.__name__, self.__dict__)


class GameState(enum.Enum):
    INITIAL = 0
    ROUND_PRE_FLOP = 1  # No cards on the table.
    ROUND_FLOP = 2  # Three cards.
    ROUND_TURN = 3  # Four cards.
    ROUND_RIVER = 4  # Five cards.
    FINISHED = 5  # The end.


class PlayerAction(enum.Enum):
    CHECK = "✅ چک"
    CALL = "(call)"
    FOLD = "❌ فولد"
    RAISE_RATE = "raise rate"
    BET = "bet"
    ALL_IN = "All-In"
    SMALL = 10
    NORMAL = 25
    BIG = 50
    RAISE_CUSTOM = "custom_raise"
    BACK_TO_MENU = "back_to_menu"


class UserException(Exception):
    pass


class Tournament:
    def __init__(self, name: str, buy_in: int, prize_pool: int, max_players: int = 8):
        self.id = str(uuid4())
        self.name = name
        self.buy_in = buy_in
        self.prize_pool = prize_pool
        self.max_players = max_players
        self.players: List[Player] = []
        self.active_games: List[Game] = []
        self.start_time: Optional[datetime.datetime] = datetime.datetime.now()
        self.end_time: Optional[datetime.datetime] = None
        self.status = "pending"  # pending, running, finished
        self.payout_structure: List[float] = [0.5, 0.3, 0.2]  # 1st place: 50%, 2nd: 30%, 3rd: 20%


class PlayerStats:
    def __init__(self, user_id: UserId):
        self.user_id = user_id
        self.total_games_played = 0
        self.total_games_won = 0
        self.total_money_earned = 0
        self.total_money_spent = 0
        self.best_hand_won = None
        self.total_tournaments_joined = 0
        self.total_tournaments_won = 0
        self.current_winning_streak = 0
        self.best_winning_streak = 0
        self.total_time_played = datetime.timedelta()
        self.registered_at = datetime.datetime.now()
        self.last_game_played_at = None
        self.total_folded = 0
        self.total_raised = 0
        self.total_called = 0
        self.total_checked = 0