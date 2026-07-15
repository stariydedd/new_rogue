import asyncio
import random
import time

import pygame
from datalayer.dataSource import load_leaderboard, save_run
from datalayer.leaderboard_client import fetch_leaderboard, run_payload, submit_run
from domain.businessLogic import (
    can_move_to,
    check_exit,
    check_item_pickup,
    drop_item_near_player,
    item_stat_label,
    move_person_x,
    move_person_y,
)
from domain.combat import process_enemy_turns
from domain.consts import MAX_LEVELS
from domain.domain import ItemType, Session

from presentation import webenv

MAX_NAME_LENGTH = 16
RUN_LIMIT = 200  # предохранитель от бесконечного бега

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
            # Режим «бег»: следующая клавиша-направление запускает серию ходов,
            # любая другая — отменяет.
            self.pending_run = False
            direction = self.DIRECTION_KEYS.get(key)
            if direction and not sleeping:
                self._run_direction(*direction)
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

    def _run_direction(self, dx, dy):
        """Бег (find из оригинального Rogue): серия ходов в направлении до упора.

        Каждый шаг — полноценный ход (враги ходят). Бег по комнате
        останавливается на клетке перед дверью впереди и у двери, мимо
        которой пробегает (проём сбоку); но если игрок уже стоит вплотную
        к двери, F в её сторону проносит через дверь и дальше по коридору.
        Коридорный бег следует поворотам и заканчивается в дверном проёме
        на том конце (дверь — конец коридора). Также стоп: стена или
        развилка, враг, портал впереди (на бегу не спускаемся), полученный
        урон, подобранный предмет, сон или конец игры. Если первый же шаг
        невозможен — «Can't move that way.» без движения."""
        session = self.session
        person = session.get_player()
        opponents = session.get_opponents()
        for step in range(RUN_LIMIT):
            if self.state != "PLAYING" or person.special_state.get("sleeping"):
                break
            nx, ny = person.crd.x + dx, person.crd.y + dy
            if any(op.is_alive() and op.crd.x == nx and op.crd.y == ny for op in opponents):
                break
            level_exit = session.get_exit()
            if level_exit.x == nx and level_exit.y == ny:
                session.set_message("You stop at the portal.")
                break
            entering_door = self._is_door_cell(nx, ny)
            from_room = self._is_room_cell(person.crd.x, person.crd.y)
            if entering_door and from_room and step:
                break  # разбежались по комнате — стоп перед дверью, не в ней
            if not can_move_to(nx, ny, session):
                # Поворот коридора — только когда уже бежим: нажатие в сторону
                # стены не должно начинать бег вбок.
                turn = self._corridor_turn(dx, dy) if step else None
                if turn:
                    dx, dy = turn
                    continue
                if step == 0:
                    session.set_message("Can't move that way.")
                break
            hp_before = person.health
            items_before = len(person.backpack.items)
            moved = move_person_x(session, dx) if dx else move_person_y(session, dy)
            if not moved:
                break
            self._resolve_turn(False)
            if person.health < hp_before or len(person.backpack.items) != items_before:
                break
            if entering_door and not from_room:
                break  # прибежали по коридору в дверной проём — конец коридора
            # Стоп у бокового проёма — только в комнате: в коридоре дверь
            # сбоку от поворота — это его собственное продолжение, и бег
            # должен доехать до проёма, а не встать на углу.
            if self._door_beside(dx, dy) and self._is_room_cell(person.crd.x, person.crd.y):
                break  # пробегаем мимо прохода — стоп у двери

    def _door_beside(self, dx, dy):
        """Дверь сбоку от направления движения — игрок пробегает мимо проёма."""
        person = self.session.get_player()
        x, y = person.crd.x, person.crd.y
        sides = ((x, y - 1), (x, y + 1)) if dx else ((x - 1, y), (x + 1, y))
        return any(self._is_door_cell(sx, sy) for sx, sy in sides)

    def _is_room_cell(self, x, y):
        """Клетка пола комнаты (двери и коридоры не считаются)."""
        return any(room is not None
                   and room.crd.x <= x < room.crd.x + room.width
                   and room.crd.y <= y < room.crd.y + room.height
                   for room in self.session.get_rooms())

    def _is_door_cell(self, x, y):
        """Клетка двери: центральная линия коридора, лежащая на стене комнаты."""
        session = self.session
        if not any(px + 1 <= x < px + pw - 1 and py + 1 <= y < py + ph - 1
                   for px, py, pw, ph in session.get_passages()):
            return False
        for room in session.get_rooms():
            if room is None:
                continue
            rx, ry, rw, rh = room.crd.x, room.crd.y, room.width, room.height
            if (x == rx - 1 or x == rx + rw) and ry <= y < ry + rh:
                return True
            if (y == ry - 1 or y == ry + rh) and rx <= x < rx + rw:
                return True
        return False

    def _is_corridor_cell(self, x, y):
        """Клетка тропы: внутри сегмента коридора и не на полу комнаты (двери — да)."""
        session = self.session
        for px, py, pw, ph in session.get_passages():
            if px + 1 <= x < px + pw - 1 and py + 1 <= y < py + ph - 1:
                for room in session.get_rooms():
                    if room is not None and (
                        room.crd.x <= x < room.crd.x + room.width
                        and room.crd.y <= y < room.crd.y + room.height
                    ):
                        return False
                return True
        return False

    def _corridor_turn(self, dx, dy):
        """Возвращает новое направление на повороте коридора или None.

        Поворот выполняется, только если игрок стоит на тропе и ровно одно
        направление (кроме обратного) продолжает её — развилки останавливают бег."""
        person = self.session.get_player()
        if not self._is_corridor_cell(person.crd.x, person.crd.y):
            return None
        options = []
        for ndx, ndy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            if (ndx, ndy) == (-dx, -dy):
                continue
            tx, ty = person.crd.x + ndx, person.crd.y + ndy
            if self._is_corridor_cell(tx, ty) and can_move_to(tx, ty, self.session):
                options.append((ndx, ndy))
        return options[0] if len(options) == 1 else None

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
