import asyncio
import random
import time

import pygame
from datalayer.dataSource import load_leaderboard, save_run
from datalayer.leaderboard_client import fetch_leaderboard, run_payload, submit_run
from domain.businessLogic import (
    check_exit,
    check_item_pickup,
    drop_item_near_player,
    item_stat_label,
    move_person_x,
    move_person_y,
    run_direction,
)
from domain.combat import process_enemy_turns
from domain.consts import MAX_LEVELS
from domain.domain import ItemType, Session

from presentation import webenv

MAX_NAME_LENGTH = 16

MAIN_MENU_OPTIONS = [("New Game", "new"), ("Leaderboard", "scoreboard"), ("Help", "help")]
QUIT_OPTIONS = [("Return to Menu", "menu"), ("Cancel", "cancel")]

_ITEM_TYPE_NAMES = {ItemType.FOOD: "food", ItemType.ELIXIR: "elixirs", ItemType.SCROLL: "scrolls"}
_ITEM_TYPE_STAT_KEY = {ItemType.FOOD: "food_used", ItemType.ELIXIR: "elixirs_used", ItemType.SCROLL: "scrolls_read"}


class Game:
    """Конечный автомат состояний игры: меню, игровой процесс, диалоги, экраны конца игры.

    Заменяет блокирующие curses-циклы (stdscr.getkey()) на обработку одного
    pygame-события за раз, вызываемую из главного цикла в main.py.
    """

    def __init__(self, touch_mode=False):
        self.state = "MAIN_MENU"
        self.session = None
        self.touch_mode = touch_mode
        self.menu_selected = 0
        self.menu_message = ""
        self.quit_selected = 0
        self.item_menu_type = None
        self.item_menu_items = []
        self.item_menu_allow_zero = False
        self.item_menu_selected = 0
        self.leaderboard_records = []
        self.leaderboard_source = ""
        self.help_return_state = "MAIN_MENU"
        self.player_name = ""
        self.name_input = ""
        self.submit_status = ""
        self.pending_run = False
        self.should_quit = False

    # --- переходы между состояниями ---

    def start_new_game(self):
        """Начинает новую игровую сессию.

        Генератор случайных чисел сеется реальными часами: в браузере (WASM)
        интерпретатор стартует в одинаковом состоянии на каждой загрузке
        страницы, и без этого первый уровень всегда получал один и тот же сид.
        """
        random.seed(time.time_ns() ^ pygame.time.get_ticks())
        self.session = Session()
        self.state = "PLAYING"

    def open_leaderboard(self):
        """Открывает экран рекордов и асинхронно тянет глобальный топ с сервера."""
        self.leaderboard_records = None  # None = ещё грузится
        self.leaderboard_source = ""
        self.state = "LEADERBOARD"
        asyncio.ensure_future(self._load_leaderboard())

    async def _load_leaderboard(self):
        records = await fetch_leaderboard()
        if records is not None:
            self.leaderboard_records = records
            self.leaderboard_source = "GLOBAL"
        else:
            # Сервер недоступен — показываем локальные рекорды этой машины.
            self.leaderboard_records = load_leaderboard()
            self.leaderboard_source = "LOCAL (server unavailable)"

    async def _submit_score(self, payload):
        result = await submit_run(payload)
        if result is not None:
            self.submit_status = "Score submitted to global leaderboard!"
        else:
            self.submit_status = "Server unavailable - score saved locally."

    # --- обработка событий по состояниям ---

    def handle_event(self, event):
        """Обрабатывает одно pygame-событие в зависимости от текущего состояния."""
        if event.type != pygame.KEYDOWN:
            return
        key = event.key
        if self.state == "MAIN_MENU":
            self._handle_main_menu(key)
        elif self.state == "NAME_ENTRY":
            self._handle_name_entry(event)
        elif self.state == "PLAYING":
            self._handle_playing(key)
        elif self.state == "ITEM_MENU":
            self._handle_item_menu(key)
        elif self.state == "QUIT_DIALOG":
            self._handle_quit_dialog(key)
        elif self.state == "LEADERBOARD":
            self.state = "MAIN_MENU"
        elif self.state == "HELP":
            self.state = self.help_return_state
        elif self.state in ("DEATH", "WIN"):
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._return_to_menu()

    def _return_to_menu(self):
        """Сбрасывает игровую сессию и возвращается в главное меню."""
        self.session = None
        self.menu_selected = 0
        self.state = "MAIN_MENU"

    def _handle_main_menu(self, key):
        if self.menu_message:
            self.menu_message = ""
            return
        if key in (pygame.K_UP, pygame.K_w):
            self.menu_selected = (self.menu_selected - 1) % len(MAIN_MENU_OPTIONS)
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.menu_selected = (self.menu_selected + 1) % len(MAIN_MENU_OPTIONS)
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            choice = MAIN_MENU_OPTIONS[self.menu_selected][1]
            if choice == "new":
                # На тач-устройстве экранная клавиатура над канвасом не
                # всплывает — имя спрашивает системный prompt() браузера.
                if self.touch_mode and webenv.is_web():
                    name = webenv.prompt_text("Name for the leaderboard (empty = anonymous):",
                                              self.player_name)
                    if name is None:
                        return  # отмена — остаёмся в меню
                    self.player_name = name.strip()[:MAX_NAME_LENGTH]
                    self.start_new_game()
                    return
                self.name_input = self.player_name
                self.state = "NAME_ENTRY"
            elif choice == "scoreboard":
                self.open_leaderboard()
            elif choice == "help":
                self.help_return_state = "MAIN_MENU"
                self.state = "HELP"

    def _handle_name_entry(self, event):
        if event.key == pygame.K_ESCAPE:
            self.state = "MAIN_MENU"
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.player_name = self.name_input.strip()
            self.start_new_game()
        elif event.key == pygame.K_BACKSPACE:
            self.name_input = self.name_input[:-1]
        elif event.unicode and event.unicode.isprintable() and len(self.name_input) < MAX_NAME_LENGTH:
            self.name_input += event.unicode

    DIRECTION_KEYS = {
        pygame.K_w: (0, -1), pygame.K_UP: (0, -1),
        pygame.K_s: (0, 1), pygame.K_DOWN: (0, 1),
        pygame.K_a: (-1, 0), pygame.K_LEFT: (-1, 0),
        pygame.K_d: (1, 0), pygame.K_RIGHT: (1, 0),
    }

    def _handle_playing(self, key):
        session = self.session
        person = session.get_player()
        sleeping = person.special_state.get("sleeping", False)
        session.message = ""
        acted = False

        if self.pending_run:
            # Режим «бег»: следующая клавиша-направление запускает серию ходов
            # (правила — в domain.businessLogic.run_direction), любая другая —
            # отменяет. Во сне попытка бега тратит ход, как и обычный шаг, —
            # иначе сон не тикал бы.
            self.pending_run = False
            direction = self.DIRECTION_KEYS.get(key)
            if direction:
                if sleeping:
                    self._resolve_turn(True)
                else:
                    run_direction(self.session, *direction)
                    self._check_game_over()
            return

        if key == pygame.K_q:
            self.quit_selected = 0
            self.state = "QUIT_DIALOG"
            return
        elif key == pygame.K_F1:
            self.help_return_state = "PLAYING"
            self.state = "HELP"
            return
        elif key == pygame.K_f:
            self.pending_run = True
            session.set_message("Run: press a direction key.")
            return
        elif key in (pygame.K_w, pygame.K_UP):
            acted = sleeping or move_person_y(session, -1)
        elif key in (pygame.K_s, pygame.K_DOWN):
            acted = sleeping or move_person_y(session, 1)
        elif key in (pygame.K_a, pygame.K_LEFT):
            acted = sleeping or move_person_x(session, -1)
        elif key in (pygame.K_d, pygame.K_RIGHT):
            acted = sleeping or move_person_x(session, 1)
        elif key == pygame.K_h:
            acted = sleeping or self._open_item_menu(ItemType.WEAPON)
        elif key == pygame.K_j:
            acted = sleeping or self._open_item_menu(ItemType.FOOD)
        elif key == pygame.K_k:
            acted = sleeping or self._open_item_menu(ItemType.ELIXIR)
        elif key == pygame.K_e:
            acted = sleeping or self._open_item_menu(ItemType.SCROLL)

        if acted:
            self._resolve_turn(sleeping)

    def _resolve_turn(self, sleeping):
        """Завершает ход: подбор предметов, проверка выхода/сохранения, ход врагов, конец игры."""
        session = self.session
        if sleeping:
            session.set_message("You are asleep!")
        check_item_pickup(session)
        check_exit(session)
        process_enemy_turns(session)
        self._check_game_over()

    def _check_game_over(self):
        session = self.session
        if not session.get_player().is_alive():
            self._finish_run("DEATH")
        elif session.level_num > MAX_LEVELS:
            self._finish_run("WIN")

    def _finish_run(self, end_state):
        """Завершает забег: локальный рекорд, отправка на сервер, экран конца игры."""
        save_run(self.session)
        payload = run_payload(self.session, self.player_name)
        self.submit_status = "Submitting score..."
        asyncio.ensure_future(self._submit_score(payload))
        self.state = end_state

    def _open_item_menu(self, item_type):
        """Открывает меню выбора предмета нужного типа. Ход завершается только после выбора."""
        person = self.session.get_player()
        if item_type == ItemType.WEAPON:
            items = [it for it in person.backpack.items if it.type == ItemType.WEAPON]
            if not items and not person.weapon:
                self.session.set_message("No weapons in backpack.")
                return False
            self.item_menu_allow_zero = True
        else:
            items = [it for it in person.backpack.items if it.type == item_type]
            if not items:
                self.session.set_message(f"No {_ITEM_TYPE_NAMES.get(item_type, 'items')} in backpack.")
                return False
            self.item_menu_allow_zero = False
        self.item_menu_items = items
        self.item_menu_type = item_type
        self.item_menu_selected = 0
        self.state = "ITEM_MENU"
        return False

    def _handle_item_menu(self, key):
        """Выбор предмета: цифры либо стрелки/крестовина + Enter.

        Индекс выбранной строки совпадает с choice: при allow_zero строка 0 —
        «голые руки», дальше предметы; без него строки нумеруются с первого
        предмета."""
        if key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
            self.state = "PLAYING"
            return
        rows = len(self.item_menu_items) + (1 if self.item_menu_allow_zero else 0)
        choice = None
        if key in (pygame.K_UP, pygame.K_w):
            self.item_menu_selected = (self.item_menu_selected - 1) % rows
            return
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.item_menu_selected = (self.item_menu_selected + 1) % rows
            return
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            choice = self.item_menu_selected
        elif self.item_menu_allow_zero and key == pygame.K_0:
            choice = 0
        elif pygame.K_1 <= key <= pygame.K_9:
            idx = key - pygame.K_0
            if idx <= len(self.item_menu_items):
                choice = idx if self.item_menu_allow_zero else idx - 1
        if choice is None:
            return
        self._apply_item_choice(choice)
        self.state = "PLAYING"
        self._resolve_turn(False)

    def _apply_item_choice(self, choice):
        session = self.session
        person = session.get_player()
        item_type = self.item_menu_type
        if item_type == ItemType.WEAPON:
            if choice == 0:
                weapon = person.unequip_weapon()
                if weapon:
                    if not person.backpack.add_item(weapon):
                        person.weapon = weapon
                        session.set_message("Backpack full! Cannot holster weapon.")
                    else:
                        session.set_message(f"You holstered {weapon.name}.")
                return
            backpack_weapons = [it for it in person.backpack.items if it.type == ItemType.WEAPON]
            real_index = next(i for i, it in enumerate(person.backpack.items) if it is backpack_weapons[choice - 1])
            old_weapon = person.equip_weapon(real_index)
            selected = person.weapon
            msg = f"You equipped {selected.name} [+{selected.strength_effect} STR]."
            if old_weapon:
                drop_item_near_player(session, old_weapon)
                msg += f" Dropped {old_weapon.name}."
            session.set_message(msg)
        else:
            items = [it for it in person.backpack.items if it.type == item_type]
            item = items[choice]
            real_index = next(i for i, it in enumerate(person.backpack.items) if it is item)
            person.use_item(real_index)
            session.set_message(f"You used {item.name}{item_stat_label(item)}.")
            stat_key = _ITEM_TYPE_STAT_KEY.get(item_type)
            if stat_key:
                session.stats[stat_key] += 1

    def _handle_quit_dialog(self, key):
        if key in (pygame.K_UP, pygame.K_w):
            self.quit_selected = (self.quit_selected - 1) % len(QUIT_OPTIONS)
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.quit_selected = (self.quit_selected + 1) % len(QUIT_OPTIONS)
        elif key == pygame.K_ESCAPE:
            self.state = "PLAYING"
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            choice = QUIT_OPTIONS[self.quit_selected][1]
            if choice == "menu":
                self._return_to_menu()
            else:
                self.state = "PLAYING"
