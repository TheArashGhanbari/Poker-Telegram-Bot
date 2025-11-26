#!/usr/bin/env python3

import logging
import threading
import time
import telebot
from typing import Callable

from pokerapp.config import Config
from pokerapp.db import SQLiteDB
from pokerapp.pokerbotcontrol import PokerBotCotroller
from pokerapp.pokerbotmodel import PokerBotModel
from pokerapp.pokerbotview import PokerBotViewer
from pokerapp.entities import ChatId


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


class MessageDelayBot(telebot.TeleBot):
    def __init__(
        self,
        token: str,
        tasks_delay=3,
    ):
        super(MessageDelayBot, self).__init__(token=token)

        self._chat_tasks_lock = threading.Lock()
        self._tasks_delay = tasks_delay
        self._chat_tasks = {}
        self._stop_chat_tasks = threading.Event()
        self._chat_tasks_thread = threading.Thread(
            target=self._tasks_manager_loop,
            args=(self._stop_chat_tasks, ),
        )

    def run_tasks_manager(self) -> None:
        self._chat_tasks_thread.start()

    def _process_chat_tasks(self) -> None:
        now = time.time()

        for (chat_id, time_tasks) in self._chat_tasks.items():
            task_time = time_tasks.get("last_time", 0)
            tasks = time_tasks.get("tasks", [])

            if now - task_time < self._tasks_delay:
                continue

            if len(tasks) == 0:
                continue

            task_callable = tasks.pop()

            try:
                task_callable()
            except Exception:
                tasks.insert(0, task_callable)
            finally:
                self._chat_tasks[chat_id]["last_time"] = now

    def _tasks_manager_loop(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            self._chat_tasks_lock.acquire()
            try:
                self._process_chat_tasks()
            finally:
                self._chat_tasks_lock.release()
            time.sleep(0.05)

    def __del__(self):
        try:
            self._stop_chat_tasks.set()
            self._chat_tasks_thread.join()
        except Exception as e:
            logging.error(e)

    def _add_task(self, chat_id: ChatId, task: Callable) -> None:
        self._chat_tasks_lock.acquire()
        try:
            if chat_id not in self._chat_tasks:
                self._chat_tasks[chat_id] = {"last_time": 0, "tasks": []}
            self._chat_tasks[chat_id]["tasks"].insert(0, task)
        finally:
            self._chat_tasks_lock.release()

    def send_photo_delayed(self, *args, **kwargs) -> None:
        chat_id = kwargs.get("chat_id", 0)
        if chat_id == 0 and len(args) > 0:
            chat_id = args[0]
        self._add_task(
            chat_id=chat_id,
            task=lambda:
                super(MessageDelayBot, self).send_photo(*args, **kwargs),
        )

    def send_message_delayed(self, *args, **kwargs) -> None:
        chat_id = kwargs.get("chat_id", 0)
        if chat_id == 0 and len(args) > 0:
            chat_id = args[0]
        self._add_task(
            chat_id=chat_id,
            task=lambda:
                super(MessageDelayBot, self).send_message(*args, **kwargs),
        )

    def edit_message_reply_markup_delayed(self, *args, **kwargs) -> None:
        def task():
            super(MessageDelayBot, self).edit_message_reply_markup(
                *args,
                **kwargs,
            )

        try:
            task()
        except Exception:
            chat_id = kwargs.get("chat_id", 0)
            if chat_id == 0 and len(args) > 0:
                # Try to extract chat_id from args if possible
                chat_id = 0  # fallback value
            self._add_task(
                chat_id=chat_id,
                task=task,
            )


class PokerBot:
    def __init__(
        self,
        token: str,
        cfg: Config,
    ):
        self._bot = MessageDelayBot(token=token)
        self._bot.run_tasks_manager()

        kv = SQLiteDB(db_path=cfg.DB_PATH)

        self._view = PokerBotViewer(bot=self._bot)
        self._model = PokerBotModel(
            view=self._view,
            bot=self._bot,
            kv=kv,
            cfg=cfg,
        )
        self._controller = PokerBotCotroller(self._model, self._bot)

    def run(self) -> None:
        self._bot.polling(none_stop=True)
