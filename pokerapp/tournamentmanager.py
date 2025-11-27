#!/usr/bin/env python3

import datetime
import threading
from typing import Dict, List, Optional
from uuid import uuid4

from pokerapp.entities import ChatId, UserId, Money
from pokerapp.improved_entities import Tournament, Player


class TournamentManager:
    def __init__(self):
        self.tournaments: Dict[str, Tournament] = {}
        self.chat_tournaments: Dict[ChatId, List[str]] = {}  # Maps chat IDs to tournament IDs
        self._lock = threading.Lock()

    def create_tournament(self, name: str, buy_in: Money, prize_pool: Money, max_players: int = 8, chat_id: ChatId = None) -> Tournament:
        """Create a new tournament"""
        tournament = Tournament(name, buy_in, prize_pool, max_players)
        
        with self._lock:
            self.tournaments[tournament.id] = tournament
            if chat_id:
                if chat_id not in self.chat_tournaments:
                    self.chat_tournaments[chat_id] = []
                self.chat_tournaments[chat_id].append(tournament.id)
        
        return tournament

    def get_tournament(self, tournament_id: str) -> Optional[Tournament]:
        """Get a tournament by ID"""
        return self.tournaments.get(tournament_id)

    def get_chat_tournaments(self, chat_id: ChatId) -> List[Tournament]:
        """Get all tournaments in a specific chat"""
        tournament_ids = self.chat_tournaments.get(chat_id, [])
        return [self.tournaments[tid] for tid in tournament_ids if tid in self.tournaments]

    def join_tournament(self, tournament_id: str, player: Player) -> bool:
        """Add a player to a tournament"""
        tournament = self.get_tournament(tournament_id)
        if not tournament or tournament.status != "pending":
            return False
        
        if len(tournament.players) >= tournament.max_players:
            return False
        
        # Check if player already joined
        for p in tournament.players:
            if p.user_id == player.user_id:
                return False  # Player already joined
        
        # Check if player has enough money
        if player.wallet.value() < tournament.buy_in:
            return False
        
        tournament.players.append(player)
        
        # Deduct buy-in from player's wallet
        player.wallet.inc(-tournament.buy_in)
        
        # Update prize pool if it's a real money tournament
        if tournament.buy_in > 0:
            tournament.prize_pool += tournament.buy_in
            
        return True

    def start_tournament(self, tournament_id: str) -> bool:
        """Start a tournament"""
        tournament = self.get_tournament(tournament_id)
        if not tournament or len(tournament.players) < 2:
            return False
        
        tournament.status = "running"
        tournament.start_time = datetime.datetime.now()
        
        # Create initial games based on number of players
        # In a real implementation, this would create multiple tables for large tournaments
        return True

    def finish_tournament(self, tournament_id: str, winner_ids: List[UserId]) -> bool:
        """Finish a tournament and distribute prizes"""
        tournament = self.get_tournament(tournament_id)
        if not tournament or tournament.status != "running":
            return False
        
        tournament.status = "finished"
        tournament.end_time = datetime.datetime.now()
        tournament.winner_user_id = winner_ids[0] if winner_ids else None
        
        # Distribute prizes based on payout structure
        total_prize = tournament.prize_pool
        for i, user_id in enumerate(winner_ids):
            if i < len(tournament.payout_structure):
                prize = int(total_prize * tournament.payout_structure[i])
                # Find the player and award the prize
                for p in tournament.players:
                    if p.user_id == user_id:
                        p.wallet.inc(prize)
                        break
        
        return True

    def remove_tournament(self, tournament_id: str):
        """Remove a tournament"""
        if tournament_id in self.tournaments:
            del self.tournaments[tournament_id]
            # Remove from chat mappings as well
            for chat_id, tournament_ids in self.chat_tournaments.items():
                if tournament_id in tournament_ids:
                    tournament_ids.remove(tournament_id)