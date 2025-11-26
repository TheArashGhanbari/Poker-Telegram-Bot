import sqlite3
import threading
from typing import Union, Optional
from pokerapp.entities import ChatId, MessageId, UserId


class SQLiteDB:
    def __init__(self, db_path: str = "pokerbot.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._get_connection() as conn:
            # Create tables for user wallets, private chats, and message queues
            conn.execute('''
                CREATE TABLE IF NOT EXISTS wallets (
                    user_id TEXT PRIMARY KEY,
                    balance INTEGER NOT NULL DEFAULT 1000
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS private_chats (
                    user_id TEXT PRIMARY KEY,
                    chat_id TEXT
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS daily_bonuses (
                    user_id TEXT PRIMARY KEY,
                    date TEXT NOT NULL
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS message_queues (
                    user_id TEXT,
                    message_id TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, message_id)
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS authorized_money (
                    user_id TEXT,
                    game_id TEXT,
                    amount INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, game_id)
                )
            ''')

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # This allows us to access columns by name
        return conn

    def get(self, key: str) -> Optional[Union[str, int, bytes]]:
        """Get a value by key. Key format should be like 'pokerbot:user_id'"""
        with self._lock:
            with self._get_connection() as conn:
                # Parse key to determine which table and column to query
                if key.startswith('pokerbot:chats:'):
                    user_id = key.replace('pokerbot:chats:', '')
                    cursor = conn.execute(
                        'SELECT chat_id FROM private_chats WHERE user_id = ?',
                        (user_id,)
                    )
                    row = cursor.fetchone()
                    return row['chat_id'].encode('utf-8') if row and row['chat_id'] else None
                elif key.startswith('pokerbot:') and ':' not in key[9:]:  # 'pokerbot:user_id' format
                    user_id = key.replace('pokerbot:', '')
                    cursor = conn.execute(
                        'SELECT balance FROM wallets WHERE user_id = ?',
                        (user_id,)
                    )
                    row = cursor.fetchone()
                    return str(row['balance']).encode('utf-8') if row else None
                elif key.startswith('pokerbot:') and ':daily' in key:
                    user_id = key.replace('pokerbot:', '').replace(':daily', '')
                    cursor = conn.execute(
                        'SELECT date FROM daily_bonuses WHERE user_id = ?',
                        (user_id,)
                    )
                    row = cursor.fetchone()
                    return row['date'].encode('utf-8') if row and row['date'] else None
                else:
                    # Key not recognized or implemented
                    return None

    def set(self, key: str, value: Union[str, int, bytes]) -> bool:
        """Set a value by key. Key format should be like 'pokerbot:user_id'"""
        if isinstance(value, bytes):
            value = value.decode('utf-8')
        
        with self._lock:
            with self._get_connection() as conn:
                if key.startswith('pokerbot:chats:'):
                    user_id = key.replace('pokerbot:chats:', '')
                    conn.execute(
                        'INSERT OR REPLACE INTO private_chats (user_id, chat_id) VALUES (?, ?)',
                        (user_id, value)
                    )
                    conn.commit()
                elif key.startswith('pokerbot:') and ':' not in key[9:]:  # 'pokerbot:user_id' format
                    user_id = key.replace('pokerbot:', '')
                    conn.execute(
                        'INSERT OR REPLACE INTO wallets (user_id, balance) VALUES (?, ?)',
                        (user_id, int(value))
                    )
                    conn.commit()
                elif key.startswith('pokerbot:') and ':daily' in key:
                    user_id = key.replace('pokerbot:', '').replace(':daily', '')
                    conn.execute(
                        'INSERT OR REPLACE INTO daily_bonuses (user_id, date) VALUES (?, ?)',
                        (user_id, value)
                    )
                    conn.commit()
                else:
                    # Key not recognized or implemented
                    return False
            return True

    def delete(self, *keys) -> int:
        """Delete keys and return the number of keys deleted"""
        deleted = 0
        with self._lock:
            with self._get_connection() as conn:
                for key in keys:
                    if key.startswith('pokerbot:chats:'):
                        if ':messages' in key:
                            # Delete from message_queues table
                            user_id = key.replace('pokerbot:chats:', '').replace(':messages', '')
                            cursor = conn.execute(
                                'DELETE FROM message_queues WHERE user_id = ?', 
                                (user_id,)
                            )
                            deleted += cursor.rowcount
                        else:
                            # Delete from private_chats table
                            user_id = key.replace('pokerbot:chats:', '')
                            cursor = conn.execute(
                                'DELETE FROM private_chats WHERE user_id = ?', 
                                (user_id,)
                            )
                            deleted += cursor.rowcount
                    elif key.startswith('pokerbot:') and ':' not in key[9:]:  # 'pokerbot:user_id' format
                        user_id = key.replace('pokerbot:', '')
                        cursor = conn.execute(
                            'DELETE FROM wallets WHERE user_id = ?', 
                            (user_id,)
                        )
                        deleted += cursor.rowcount
                    elif key.startswith('pokerbot:') and ':daily' in key:
                        user_id = key.replace('pokerbot:', '').replace(':daily', '')
                        cursor = conn.execute(
                            'DELETE FROM daily_bonuses WHERE user_id = ?', 
                            (user_id,)
                        )
                        deleted += cursor.rowcount
                conn.commit()
        return deleted

    def rpop(self, key: str) -> Optional[bytes]:
        """Pop from the right side of a list (simulating Redis list behavior)"""
        if key.startswith('pokerbot:chats:') and ':messages' in key:
            user_id = key.replace('pokerbot:chats:', '').replace(':messages', '')
            with self._lock:
                with self._get_connection() as conn:
                    # Get the oldest message for this user (by timestamp)
                    cursor = conn.execute(
                        'SELECT message_id FROM message_queues WHERE user_id = ? ORDER BY timestamp ASC LIMIT 1',
                        (user_id,)
                    )
                    row = cursor.fetchone()
                    if row:
                        message_id = row['message_id']
                        # Delete the message after popping
                        conn.execute(
                            'DELETE FROM message_queues WHERE user_id = ? AND message_id = ?',
                            (user_id, message_id)
                        )
                        conn.commit()
                        return message_id.encode('utf-8')
        return None

    def rpush(self, key: str, *values) -> int:
        """Push values to the right side of a list (simulating Redis list behavior)"""
        if key.startswith('pokerbot:chats:') and ':messages' in key:
            user_id = key.replace('pokerbot:chats:', '').replace(':messages', '')
            with self._lock:
                with self._get_connection() as conn:
                    for value in values:
                        if isinstance(value, bytes):
                            value = value.decode('utf-8')
                        conn.execute(
                            'INSERT INTO message_queues (user_id, message_id) VALUES (?, ?)',
                            (user_id, value)
                        )
                    conn.commit()
                    return len(values)
        return 0

    def incrby(self, key: str, increment: int) -> int:
        """Increment the value of a key by the given amount"""
        with self._lock:
            with self._get_connection() as conn:
                if key.startswith('pokerbot:') and ':' not in key[9:]:  # 'pokerbot:user_id' format
                    user_id = key.replace('pokerbot:', '')
                    # Get current value
                    cursor = conn.execute(
                        'SELECT balance FROM wallets WHERE user_id = ?', 
                        (user_id,)
                    )
                    row = cursor.fetchone()
                    current_value = row['balance'] if row else 0
                    
                    # Calculate new value
                    new_value = current_value + increment
                    
                    # Update the database
                    conn.execute(
                        'INSERT OR REPLACE INTO wallets (user_id, balance) VALUES (?, ?)',
                        (user_id, new_value)
                    )
                    conn.commit()
                    return new_value
        return 0

    def get_authorized_money(self, user_id: str, game_id: str) -> int:
        """Get the authorized money for a user in a specific game"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    'SELECT amount FROM authorized_money WHERE user_id = ? AND game_id = ?',
                    (user_id, game_id)
                )
                row = cursor.fetchone()
                return row['amount'] if row else 0

    def set_authorized_money(self, user_id: str, game_id: str, amount: int) -> None:
        """Set the authorized money for a user in a specific game"""
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    'INSERT OR REPLACE INTO authorized_money (user_id, game_id, amount) VALUES (?, ?, ?)',
                    (user_id, game_id, amount)
                )
                conn.commit()

    def delete_authorized_money(self, user_id: str, game_id: str) -> None:
        """Delete the authorized money record for a user in a specific game"""
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    'DELETE FROM authorized_money WHERE user_id = ? AND game_id = ?',
                    (user_id, game_id)
                )
                conn.commit()