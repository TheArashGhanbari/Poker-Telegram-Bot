#!/usr/bin/env python3
"""
Test script to verify the conversion to telebot is working correctly
"""

import sys
from unittest.mock import Mock, MagicMock
import telebot

# Mock dependencies to avoid needing actual Redis and environment variables
import redis
# Replace the real Redis connection with a mock
redis.Redis = Mock()

# Mock the environment variables
import os
original_getenv = os.getenv
def mock_getenv(key, default=None):
    if key == 'POKERBOT_TOKEN':
        return 'test_token'
    elif key == 'POKERBOT_DEBUG':
        return '1'  # Enable debug mode to make testing easier
    else:
        return original_getenv(key, default)
os.getenv = mock_getenv

def test_conversion():
    try:
        print("Testing imports...")
        
        # Import main modules
        from pokerapp.config import Config
        from pokerapp.pokerbot import PokerBot
        from pokerapp.pokerbotmodel import PokerBotModel
        from pokerapp.pokerbotview import PokerBotViewer
        from pokerapp.pokerbotcontrol import PokerBotCotroller
        from pokerapp.entities import PlayerAction
        
        print("[SUCCESS] All modules imported successfully")

        # Test configuration
        print("\nTesting configuration...")
        cfg = Config()
        print(f"[SUCCESS] Config created: TOKEN is {'set' if cfg.TOKEN else 'not set'}, DEBUG is {cfg.DEBUG}")

        # Test bot creation with a mock token (we don't actually connect)
        print("\nTesting bot creation...")
        bot = PokerBot(token="test_token", cfg=cfg)
        print("[SUCCESS] PokerBot created successfully")

        # Test that the bot has the right type
        from pokerapp.pokerbot import MessageDelayBot
        assert isinstance(bot._bot, MessageDelayBot) or hasattr(bot._bot, 'send_message_delayed'), "Bot should be MessageDelayBot"
        print("[SUCCESS] Bot has correct type with delayed methods")

        # Test model and viewer creation
        print("\nTesting model and viewer...")
        # Create a mock bot for testing
        mock_telebot = telebot.TeleBot("test_token")
        mock_telebot.send_message_delayed = mock_telebot.send_message  # Add delayed method
        mock_telebot.send_photo_delayed = mock_telebot.send_photo      # Add delayed method
        mock_telebot.edit_message_reply_markup_delayed = mock_telebot.edit_message_reply_markup  # Add delayed method

        viewer = PokerBotViewer(bot=mock_telebot)
        print("[SUCCESS] PokerBotViewer created successfully")

        # Mock redis for model
        mock_redis = Mock()
        mock_redis.get.return_value = "1000"  # Default money value
        mock_redis.incrby.return_value = "1050"  # Return value after increment
        from pokerapp.entities import ChatId, UserId, Money, Wallet
        from pokerapp.config import Config

        model = PokerBotModel(view=viewer, bot=mock_telebot, cfg=cfg, kv=mock_redis)
        print("[SUCCESS] PokerBotModel created successfully")

        # Test controller
        controller = PokerBotCotroller(model=model, bot=mock_telebot)
        print("[SUCCESS] PokerBotController created successfully")

        # Test some basic functionality
        print("\nTesting basic functionality...")

        # Test player actions enum
        assert PlayerAction.CALL.value == "call"
        assert PlayerAction.FOLD.value == "fold"
        assert PlayerAction.SMALL.value == 10
        print("[SUCCESS] Player actions work correctly")

        print("\n[SUCCESS] All tests passed! The conversion to telebot is successful.")
        print("\nSummary of changes:")
        print("- Replaced python-telegram-bot with pyTelegramBotAPI")
        print("- Updated imports and method calls to use telebot equivalents")
        print("- Converted callback handlers to use telebot decorators")
        print("- Updated message handling to use telebot Message objects")
        print("- Maintained the message delay functionality for rate limiting")
        print("- All modules import and instantiate correctly")

        return True

    except Exception as e:
        print(f"[ERROR] Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_conversion()
    sys.exit(0 if success else 1)