#!/usr/bin/env python3

import sqlite3
import threading
import datetime
from typing import Union, Optional, List
from pokerapp.entities import ChatId, MessageId, UserId, Money
from pokerapp.improved_entities import PlayerStats


class GameStatsModel:
    def __init__(self, db_path: str = "pokerbot.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_stats_db()

    def _init_stats_db(self):
        with self._get_connection() as conn:
            # Create table for player statistics
            conn.execute('''
                CREATE TABLE IF NOT EXISTS player_stats (
                    user_id TEXT PRIMARY KEY,
                    total_games_played INTEGER DEFAULT 0,
                    total_games_won INTEGER DEFAULT 0,
                    total_money_earned INTEGER DEFAULT 0,
                    total_money_spent INTEGER DEFAULT 0,
                    best_hand_won TEXT,
                    total_tournaments_joined INTEGER DEFAULT 0,
                    total_tournaments_won INTEGER DEFAULT 0,
                    current_winning_streak INTEGER DEFAULT 0,
                    best_winning_streak INTEGER DEFAULT 0,
                    total_time_played INTEGER DEFAULT 0,  -- stored as seconds
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_game_played_at TIMESTAMP,
                    total_folded INTEGER DEFAULT 0,
                    total_raised INTEGER DEFAULT 0,
                    total_called INTEGER DEFAULT 0,
                    total_checked INTEGER DEFAULT 0
                )
            ''')
            
            # Create table for game history
            conn.execute('''
                CREATE TABLE IF NOT EXISTS game_history (
                    game_id TEXT PRIMARY KEY,
                    chat_id TEXT,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
                    winner_user_id TEXT,
                    pot_amount INTEGER,
                    players_count INTEGER,
                    game_type TEXT
                )
            ''')
            
            # Create table for tournament records
            conn.execute('''
                CREATE TABLE IF NOT EXISTS tournaments (
                    tournament_id TEXT PRIMARY KEY,
                    name TEXT,
                    buy_in INTEGER,
                    prize_pool INTEGER,
                    max_players INTEGER,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
                    status TEXT,
                    winner_user_id TEXT
                )
            ''')

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # This allows us to access columns by name
        return conn

    def get_player_stats(self, user_id: str) -> PlayerStats:
        """Get player statistics for a user"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    'SELECT * FROM player_stats WHERE user_id = ?',
                    (user_id,)
                )
                row = cursor.fetchone()
                
                if row:
                    stats = PlayerStats(user_id)
                    stats.total_games_played = row['total_games_played']
                    stats.total_games_won = row['total_games_won']
                    stats.total_money_earned = row['total_money_earned']
                    stats.total_money_spent = row['total_money_spent'] 
                    stats.best_hand_won = row['best_hand_won']
                    stats.total_tournaments_joined = row['total_tournaments_joined']
                    stats.total_tournaments_won = row['total_tournaments_won']
                    stats.current_winning_streak = row['current_winning_streak']
                    stats.best_winning_streak = row['best_winning_streak']
                    stats.total_time_played = datetime.timedelta(seconds=row['total_time_played'])
                    stats.registered_at = row['registered_at']
                    stats.last_game_played_at = row['last_game_played_at']
                    stats.total_folded = row['total_folded']
                    stats.total_raised = row['total_raised']
                    stats.total_called = row['total_called']
                    stats.total_checked = row['total_checked']
                    return stats
                else:
                    # Return default stats for new player
                    return PlayerStats(user_id)

    def update_player_stats(self, user_id: str, stats: PlayerStats) -> None:
        """Update player statistics"""
        with self._lock:
            with self._get_connection() as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO player_stats (
                        user_id, total_games_played, total_games_won, 
                        total_money_earned, total_money_spent, best_hand_won,
                        total_tournaments_joined, total_tournaments_won,
                        current_winning_streak, best_winning_streak,
                        total_time_played, last_game_played_at,
                        total_folded, total_raised, total_called, total_checked
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user_id, stats.total_games_played, stats.total_games_won,
                    stats.total_money_earned, stats.total_money_spent, 
                    stats.best_hand_won, stats.total_tournaments_joined,
                    stats.total_tournaments_won, stats.current_winning_streak,
                    stats.best_winning_streak, int(stats.total_time_played.total_seconds()),
                    stats.last_game_played_at, stats.total_folded, 
                    stats.total_raised, stats.total_called, stats.total_checked
                ))
                conn.commit()

    def record_game(self, game_id: str, chat_id: str, start_time: datetime.datetime, 
                   end_time: datetime.datetime, winner_user_id: str, pot_amount: int, 
                   players_count: int, game_type: str) -> None:
        """Record a completed game in history"""
        with self._lock:
            with self._get_connection() as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO game_history (
                        game_id, chat_id, start_time, end_time, 
                        winner_user_id, pot_amount, players_count, game_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (game_id, chat_id, start_time, end_time, winner_user_id, 
                      pot_amount, players_count, game_type))
                conn.commit()

    def get_game_history(self, user_id: str, limit: int = 10) -> List[dict]:
        """Get game history for a user"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute('''
                    SELECT * FROM game_history 
                    WHERE winner_user_id = ?
                    ORDER BY start_time DESC
                    LIMIT ?
                ''', (user_id, limit))
                
                rows = cursor.fetchall()
                return [dict(row) for row in rows]

    def get_top_players(self, limit: int = 10) -> List[dict]:
        """Get top players based on win rate"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute('''
                    SELECT user_id, total_games_won, total_games_played,
                           CASE WHEN total_games_played > 0 
                                THEN total_games_won * 100.0 / total_games_played 
                                ELSE 0 END AS win_rate
                    FROM player_stats
                    ORDER BY total_games_won DESC, win_rate DESC
                    LIMIT ?
                ''', (limit,))
                
                rows = cursor.fetchall()
                return [dict(row) for row in rows]

    def increment_stat(self, user_id: str, stat_name: str, increment: int = 1) -> None:
        """Increment a specific statistic for a user"""
        with self._lock:
            with self._get_connection() as conn:
                # Update the specific statistic based on the field name
                if stat_name == 'total_games_played':
                    conn.execute('UPDATE player_stats SET total_games_played = COALESCE(total_games_played, 0) + ? WHERE user_id = ?', (increment, user_id))
                elif stat_name == 'total_games_won':
                    conn.execute('UPDATE player_stats SET total_games_won = COALESCE(total_games_won, 0) + ? WHERE user_id = ?', (increment, user_id))
                    # Also update streaks
                    conn.execute('UPDATE player_stats SET current_winning_streak = COALESCE(current_winning_streak, 0) + ? WHERE user_id = ?', (increment, user_id))
                    conn.execute('UPDATE player_stats SET best_winning_streak = MAX(COALESCE(best_winning_streak, 0), COALESCE(current_winning_streak, 0)) WHERE user_id = ?', (user_id,))
                elif stat_name == 'total_money_earned':
                    conn.execute('UPDATE player_stats SET total_money_earned = COALESCE(total_money_earned, 0) + ? WHERE user_id = ?', (increment, user_id))
                elif stat_name == 'total_money_spent':
                    conn.execute('UPDATE player_stats SET total_money_spent = COALESCE(total_money_spent, 0) + ? WHERE user_id = ?', (increment, user_id))
                elif stat_name == 'total_folded':
                    conn.execute('UPDATE player_stats SET total_folded = COALESCE(total_folded, 0) + ? WHERE user_id = ?', (increment, user_id))
                elif stat_name == 'total_raised':
                    conn.execute('UPDATE player_stats SET total_raised = COALESCE(total_raised, 0) + ? WHERE user_id = ?', (increment, user_id))
                elif stat_name == 'total_called':
                    conn.execute('UPDATE player_stats SET total_called = COALESCE(total_called, 0) + ? WHERE user_id = ?', (increment, user_id))
                elif stat_name == 'total_checked':
                    conn.execute('UPDATE player_stats SET total_checked = COALESCE(total_checked, 0) + ? WHERE user_id = ?', (increment, user_id))
                
                conn.commit()

    def update_best_hand(self, user_id: str, hand_description: str) -> None:
        """Update a player's best hand won"""
        with self._lock:
            with self._get_connection() as conn:
                conn.execute('UPDATE player_stats SET best_hand_won = ? WHERE user_id = ?', (hand_description, user_id))
                conn.commit()

    def reset_winning_streak(self, user_id: str) -> None:
        """Reset a player's winning streak"""
        with self._lock:
            with self._get_connection() as conn:
                conn.execute('UPDATE player_stats SET current_winning_streak = 0 WHERE user_id = ?', (user_id,))
                conn.commit()

    def add_play_time(self, user_id: str, play_time: datetime.timedelta) -> None:
        """Add play time to a player's total"""
        with self._lock:
            with self._get_connection() as conn:
                conn.execute('''
                    UPDATE player_stats 
                    SET total_time_played = COALESCE(total_time_played, 0) + ?,
                        last_game_played_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                ''', (int(play_time.total_seconds()), user_id))
                conn.commit()