import random
from enum import Enum

from domain import geometry
from domain.consts import *


class Coord:
    """Пара координат (x, y) на карте уровня."""

    def __init__(self, x = 0, y = 0):
        """Создаёт координату с заданными x и y."""
        self.x = x
        self.y = y

class Session:
    """Игровая сессия: текущий уровень, персонаж и статистика прохождения."""

    def __init__(self,
        level = 1,
    ):
        """Начинает новую сессию с первого (или указанного) уровня, создавая игрока и предметы."""
        self.level_num = level
        self.level = Level(level)
        person_crd = self.level.get_person_position()
        self.person = Person(crd=person_crd)
        self.level.generate_items_in_rooms(self.person)
        self.message = ""
        self.visited_rooms = set()
        self.stats = {
            "enemies_killed":  0,
            "food_used":       0,
            "elixirs_used":    0,
            "scrolls_read":    0,
            "attacks_made":    0,
            "hits_taken":      0,
            "tiles_moved":     0,
        }


    def get_rooms(self):
        """Возвращает список комнат текущего уровня."""
        return self.level.rooms

    def get_passages(self):
        """Возвращает список коридоров текущего уровня."""
        return self.level.passages

    def get_player(self):
        """Возвращает персонажа игрока."""
        return self.person

    def get_exit(self):
        """Возвращает координаты выхода на следующий уровень."""
        return self.level.exit_crd

    def get_opponents(self):
        """Возвращает всех врагов текущего уровня."""
        return self.level.get_all_opponents()

    def set_message(self, msg):
        """Устанавливает текст последнего игрового сообщения для показа в UI."""
        self.message = msg

    def update_level(self):
        """Переходит на следующий уровень: генерирует новую карту и сбрасывает посещённые комнаты."""
        self.level_num += 1
        self.level = Level(self.level_num)
        self.person.crd = self.level.get_person_position()
        self.level.generate_items_in_rooms(self.person)
        self.visited_rooms = set()

class Room:
    """Прямоугольная комната уровня со своими предметами и врагами."""

    def __init__(self, x, y, width, height):
        """Создаёт пустую комнату заданного размера и позиции."""
        self.items = []
        self.crd = Coord(x,y)
        self.width = width
        self.height = height
        self.enemies = []

    def get_subjects(self, player, count, forbidden=()):
        """Генерирует и добавляет в комнату `count` случайных предметов.

        Клетки не повторяются и не попадают в `forbidden` (например, портал —
        предмет под ним был бы не виден и подобран без сообщения)."""
        c = []
        for _ in range(count):
            item = Subject()
            item.generate_random_type(player)
            while True:
                crd = self.generate_coords()
                new_pair = (crd.x, crd.y)
                if new_pair in c or new_pair in forbidden:
                    continue
                c.append(new_pair)
                break
            item.crd = crd
            self.items.append(item)

    def generate_coords(self):
        """Возвращает случайные координаты внутри пола комнаты."""
        x = self.crd.x + random.randint(0, self.width - 2)
        y = self.crd.y + random.randint(0, self.height - 2)
        return Coord(x, y)

class Level:
    """Уровень подземелья: комнаты, коридоры, точка старта и выход на следующий уровень."""

    def __init__(self,
        level = 1,
    ):
        """Генерирует комнаты, коридоры, врагов и выход для уровня с номером `level`."""
        self.level = level
        self.seed = 0
        self.rooms = []
        self.rooms_cnt = 0
        self.passages = []
        self.start_room_idx = None
        self._generate_valid_level()
        # Двери уровня считаются один раз: их использует размещение выхода,
        # логика бега и тесты — единое определение из domain.geometry.
        self.doors = geometry.door_cells(self.rooms, self.passages)
        self._pick_start_room()
        self._generate_opponents(self.start_room_idx)
        self.exit_crd = self._get_exit_position()

    def _generate_rooms(self):
        """Случайно генерирует комнаты по сетке GRID×GRID, часть ячеек может остаться пустой."""
        self.seed = random.randrange(100, 10**10)
        random.seed(self.seed)
        rooms = []
        for r in range(GRID):
            for c in range(GRID):
                if random.random() > PROB_ROOM:
                    rooms.append(None)
                    continue

                avail_w = CELL_W - 2 * PAD
                avail_h = CELL_H - 2 * PAD
                if avail_w < MIN_W or avail_h < MIN_H:
                    rooms.append(None)
                    continue

                w = random.randint(MIN_W, min(MAX_W, avail_w))
                h = random.randint(MIN_H, min(MAX_H, avail_h))

                x = c * CELL_W + PAD + random.randint(0, avail_w - w)
                y = r * CELL_H + PAD + random.randint(0, avail_h - h)

                x = max(0, min(COLS - w, x))
                y = max(0, min(ROWS - h, y))

                rooms.append(Room(x, y, w, h))

        self.rooms_cnt = sum([1 for i in rooms if i is not None])
        return rooms

    def _generate_edges_for_rooms(self):
        """Возвращает список пар индексов соседних по сетке комнат, которые можно соединить."""
        edges = []
        for i in range(GRID):
            for j in range(GRID - 1):
                p1 = i * GRID + j
                p2 = i * GRID + j + 1
                if self.rooms[p1] is not None and self.rooms[p2] is not None:
                    edges.append([p1, p2])

        for i in range(GRID - 1):
            for j in range(GRID):
                p1 = i * GRID + j
                p2 = i * GRID + j + GRID
                if self.rooms[p1] is not None and self.rooms[p2] is not None:
                    edges.append([p1, p2])
        return edges

    def _find_set(self, v, parent):
        """Находит представителя множества (DSU) для вершины `v` со сжатием пути."""
        if (v == parent[v]):
            return v
        parent[v] = self._find_set(parent[v], parent)
        return parent[v]

    def _union_set(self, edge, parent, rank):
        """Объединяет множества (DSU) двух комнат ребра `edge` по рангу."""
        v = self._find_set(edge[0], parent)
        u = self._find_set(edge[1], parent)
        if u != v:
            if rank[u] >= rank[v]:
                parent[v] = u
            else:
                parent[u] = v
            if rank[u] == rank[v]:
                rank[u] += 1

    def _connected_set(self, edge, parent):
        """Проверяет, лежат ли обе комнаты ребра `edge` в одном множестве (DSU)."""
        return self._find_set(edge[0], parent) == self._find_set(edge[1], parent)

    def _create_passage(self, coord_x, coord_y, width, height, passages):
        """Добавляет в `passages` прямоугольный сегмент коридора, расширенный на 1 клетку по краям."""
        passage = []
        passage.append(coord_x - 1)
        passage.append(coord_y - 1)
        passage.append(width + 2)
        passage.append(height + 2)
        passages.append(passage)

    def _generate_horizontal_passage(self, edge, passages):
        """Строит коридор между двумя горизонтально соседними комнатами ребра `edge`."""
        first_coords = self.rooms[edge[0]]
        second_coords = self.rooms[edge[1]]

        first_x = first_coords.crd.x + first_coords.width

        up_range_coord = first_coords.crd.y
        bottom_range_coord = first_coords.crd.y + first_coords.height - 1
        first_y = random.randint(up_range_coord, bottom_range_coord)

        second_x = second_coords.crd.x - 1

        up_range_coord = second_coords.crd.y
        bottom_range_coord = second_coords.crd.y + second_coords.height - 1
        second_y = random.randint(up_range_coord, bottom_range_coord)

        if (first_y == second_y):
            self._create_passage(first_x, first_y, abs(second_x - first_x) + 1, 1, passages)
        else:
            vertical = random.randint(min(first_x, second_x) + 1, max(first_x, second_x) - 1)
            self._create_passage(first_x,  first_y,                abs(vertical - first_x) + 1, 1,  passages)
            self._create_passage(vertical, min(first_y, second_y), 1, abs(second_y - first_y) + 1,  passages)
            self._create_passage(vertical, second_y,               abs(second_x - vertical) + 1, 1, passages)

    def _generate_vertical_passage(self, edge, passages):
        """Строит коридор между двумя вертикально соседними комнатами ребра `edge`."""
        first_coords = self.rooms[edge[0]]
        second_coords = self.rooms[edge[1]]

        first_y = first_coords.crd.y + first_coords.height

        up_range_coord = first_coords.crd.x
        bottom_range_coord = first_coords.crd.x + first_coords.width - 1
        first_x = random.randint(up_range_coord, bottom_range_coord)

        second_y = second_coords.crd.y - 1

        up_range_coord = second_coords.crd.x
        bottom_range_coord = second_coords.crd.x + second_coords.width - 1
        second_x = random.randint(up_range_coord, bottom_range_coord)

        if first_x == second_x:
            self._create_passage(first_x, first_y, 1, abs(second_y - first_y) + 1, passages)
        else:
            horizont = random.randint(min(first_y, second_y) + 1, max(first_y, second_y) - 1)
            self._create_passage(first_x, first_y,  1, abs(horizont - first_y) + 1,  passages)
            self._create_passage(min(first_x, second_x), horizont, abs(second_x - first_x) + 1, 1,  passages)
            self._create_passage(second_x, horizont, 1, abs(second_y - horizont) + 1, passages)

    def _generate_passages(self):
        """Строит коридоры, соединяющие все комнаты в одну связную сеть (алгоритм DSU/Крускала)."""
        created_connections = 0
        passages = []
        edges = self._generate_edges_for_rooms()
        random.shuffle(edges)
        parent = [i for i in range(len(self.rooms))]
        rank = [0 for _ in range(len(self.rooms))]
        for i in range(len(edges)):
            if not self._connected_set(edges[i], parent):
                self._union_set(edges[i], parent, rank)
                created_connections += 1
                if abs(edges[i][0] - edges[i][1]) == 1:
                    self._generate_horizontal_passage(edges[i], passages)
                else:
                    self._generate_vertical_passage(edges[i], passages)
        return passages, created_connections

    def _generate_valid_level(self):
        """Перегенерирует комнаты и коридоры, пока не получится валидный связный уровень."""
        while True:
            self.rooms = self._generate_rooms()
            if self.rooms_cnt < MIN_ROOMS_COUNT:
                continue
            self.passages, created_connections = self._generate_passages()

            if created_connections == self.rooms_cnt - 1:
                break

    def _pick_start_room(self):
        """Случайно выбирает индекс стартовой комнаты уровня."""
        valid_indices = [i for i, r in enumerate(self.rooms) if r is not None]
        self.start_room_idx = random.choice(valid_indices)

    def get_person_position(self):
        """Возвращает случайные координаты внутри стартовой комнаты для игрока."""
        return self.rooms[self.start_room_idx].generate_coords()

    def _generate_opponents(self, player_room_idx):
        """Спавнит врагов во все комнаты кроме стартовой"""
        max_per_room = MAX_MONSTERS_PER_ROOM + self.level // LEVEL_UPDATE_DIFFICULTY
        for i, room in enumerate(self.rooms):
            if room is None or i == player_room_idx:
                continue
            count = random.randint(0, max_per_room)
            for _ in range(count):
                for _ in range(16):
                    crd = room.generate_coords()
                    occupied = any(op.crd.x == crd.x and op.crd.y == crd.y for op in room.enemies)
                    if not occupied:
                        opponent = Opponent()
                        opponent.generate_from_level(self.level)
                        opponent.crd = crd
                        room.enemies.append(opponent)
                        break

    def get_all_opponents(self):
        """Возвращает список всех противников на уровне"""
        opponents = []
        for room in self.rooms:
            if room is not None:
                opponents.extend(room.enemies)
        return opponents

    def _get_exit_position(self):
        """Выбирает случайную комнату (не стартовую, если возможно) и клетку выхода в ней.

        Выход не ставится вплотную к дверям (по Чебышёву > 1): портал у самого
        входа проваливал бы игрока на следующий уровень, едва он вошёл. Клетки
        пола перечисляются явно, поэтому подходящая находится всегда, когда
        она существует (в отличие от случайных проб)."""
        candidates = [(i, r) for i, r in enumerate(self.rooms) if r is not None and i != self.start_room_idx]
        if not candidates:
            candidates = [(i, r) for i, r in enumerate(self.rooms) if r is not None]
        _, room = random.choice(candidates)
        occupied = {(op.crd.x, op.crd.y) for op in room.enemies if op.is_alive()}
        floor = [(x, y)
                 for y in range(room.crd.y, room.crd.y + room.height)
                 for x in range(room.crd.x, room.crd.x + room.width)
                 if (x, y) not in occupied]
        valid = [(x, y) for x, y in floor
                 if all(max(abs(x - dx), abs(y - dy)) > 1 for dx, dy in self.doors)]
        x, y = random.choice(valid if valid else floor)
        return Coord(x, y)

    def generate_items_in_rooms(self, player):
        """Наполняет все комнаты уровня, кроме стартовой, случайными предметами."""
        rooms = [r for i, r in enumerate(self.rooms) if r is not None and i != self.start_room_idx]
        max_items = max(1, MAX_CONSUMABLES_PER_ROOM - self.level // LEVEL_UPDATE_DIFFICULTY)
        exit_cell = {(self.exit_crd.x, self.exit_crd.y)}
        for room in rooms:
            count = random.randint(0, max_items)
            room.get_subjects(player, count, forbidden=exit_cell)


class Person:
    """Персонаж игрока: характеристики, оружие, рюкзак и временные эффекты."""

    def __init__(
        self,
        crd=None,
        max_health=DEFAULT_MAX_HEALTH,
        health=DEFAULT_MAX_HEALTH,
        agility=DEFAULT_AGILITY,
        strength=DEFAULT_STRENGTH,
        weapon=DEFAULT_WEAPON,
    ):
        """Создаёт персонажа с базовыми характеристиками на заданной позиции."""
        self.crd = crd if crd is not None else Coord(-1, -1)
        self.max_health = max_health
        self.health = health
        self.agility = agility
        self.strength = strength
        self.weapon = weapon
        self.backpack = Backpack()
        self.treasures = DEFAULT_TREASURES
        self.special_state = {}
        self.active_effects = []
        self.facing = 1  # 1 — смотрит вправо, -1 — влево (последний горизонтальный шаг)

    def is_alive(self):
        """Проверяет, жив ли персонаж"""
        return self.health > 0

    def take_damage(self, damage):
        """Наносит урон персонажу"""
        self.health -= damage
        if self.health < 0:
            self.health = 0

    def heal(self, amount):
        """Лечит персонажа на указанное количество здоровья"""
        self.health += amount
        if self.health > self.max_health:
            self.health = self.max_health

    def increase_max_health(self, amount):
        """Увеличивает максимальное здоровье персонажа"""
        self.max_health += amount
        self.heal(amount)

    def increase_agility(self, amount):
        """Увеличивает ловкость персонажа"""
        self.agility += amount

    def increase_strength(self, amount):
        """Увеличивает силу персонажа"""
        self.strength += amount

    def pick_up_item(self, item):
        """Подбирает предмет и кладет в рюкзак"""
        return self.backpack.add_item(item)

    def use_item(self, item_index):
        """Использует предмет из рюкзака"""
        if 0 <= item_index < len(self.backpack.items):
            item = self.backpack.items[item_index]
            if item.type == ItemType.ELIXIR:
                self.apply_elixir_effect(item)
            else:
                self.apply_item_effects(item)
            self.backpack.remove_item_at(item_index)
            return True
        return False

    def apply_item_effects(self, item):
        """Постоянно применяет эффекты предмета к персонажу"""
        self.heal(item.health_effect)
        self.increase_max_health(item.max_health_effect)
        self.increase_agility(item.agility_effect)
        self.increase_strength(item.strength_effect)

    def apply_elixir_effect(self, item):
        """Временно применяет эффект эликсира на ELIXIR_DURATION ходов"""
        effects = [
            ("max_health", item.max_health_effect, self.increase_max_health),
            ("agility", item.agility_effect, self.increase_agility),
            ("strength", item.strength_effect, self.increase_strength),
        ]
        for stat, amount, apply in effects:
            if amount:
                apply(amount)
                self.active_effects.append({"stat": stat, "amount": amount, "turns_left": ELIXIR_DURATION})

    def tick_effects(self):
        """Уменьшает таймеры эффектов эликсиров, откатывает истёкшие"""
        remaining = []
        for effect in self.active_effects:
            effect["turns_left"] -= 1
            if effect["turns_left"] <= 0:
                stat = effect["stat"]
                amount = effect["amount"]
                if stat == "max_health":
                    self.max_health = max(1, self.max_health - amount)
                    if self.health > self.max_health:
                        self.health = max(1, self.max_health)
                elif stat == "agility":
                    self.agility -= amount
                elif stat == "strength":
                    self.strength -= amount
            else:
                remaining.append(effect)
        self.active_effects = remaining

    def equip_weapon(self, item_index):
        """Экипирует оружие из рюкзака. Убирает его из рюкзака, возвращает старое (упадёт на пол)."""
        if 0 <= item_index < len(self.backpack.items):
            item = self.backpack.items[item_index]
            self.backpack.remove_item_at(item_index)
            old_weapon = self.weapon
            self.weapon = item
            return old_weapon
        return None

    def unequip_weapon(self):
        """Снимает текущее оружие. Возвращает его (упадёт на пол), не кладёт в рюкзак."""
        weapon = self.weapon
        self.weapon = None
        return weapon

    def receive_treasure(self, amount):
        """Получает сокровища за победу над противником"""
        self.treasures += amount


class Backpack:
    """Инвентарь персонажа с ограничением на количество предметов одного типа."""

    def __init__(self):
        """Создаёт пустой рюкзак."""
        self.items = []

    def add_item(self, item):
        """Добавляет предмет в рюкзак, если не превышен лимит типа."""
        count = sum(1 for it in self.items if it.type == item.type)
        if count >= MAX_BACKPACK_ITEMS_PER_TYPE:
            return False
        self.items.append(item)
        return True

    def remove_item_at(self, index):
        """Удаляет предмет по индексу"""
        if 0 <= index < len(self.items):
            self.items.pop(index)
            return True
        return False

class OpponentType(Enum):
    """Типы врагов в игре."""

    ZOMBIE = "zombie"
    VAMPIRE = "vampire"
    GHOST = "ghost"
    OGRE = "ogre"
    SNAKE = "snake"


class Opponent:
    """Враг на уровне: характеристики, поведение преследования и паттерн движения."""

    def __init__(
        self,
        opponent_type=None,
        health=0,
        agility=0,
        strength=0,
        hostility=0
    ):
        """Создаёт врага заданного типа с базовыми характеристиками."""
        self.type = opponent_type
        self.health = health
        self.agility = agility
        self.strength = strength
        self.hostility = hostility
        self.is_chasing = False
        self.special_state = {}
        self.is_visible = True
        self.crd = Coord()
        self.last_direction = None
        self.ogre_cooldown = False
        self.vampire_first_strike = True
        self.facing = 1  # 1 — смотрит вправо, -1 — влево (последний горизонтальный шаг)

    def generate_from_level(self, level_num):
        """
        Генерирует характеристики врага на основе номера уровня.
        """
        self.type = random.choice(list(OpponentType))

        base_stats = self._get_base_stats_by_type(self.type)
        self.health = base_stats['health']
        self.agility = base_stats['agility']
        self.strength = base_stats['strength']
        self.hostility = base_stats['hostility']

        percents_update = PERCENTS_UPDATE_DIFFICULTY_MONSTERS * level_num
        scale_factor = 1 + percents_update / 100.0

        self.health = int(self.health * scale_factor)
        self.agility = int(self.agility * scale_factor)
        self.strength = int(self.strength * scale_factor)

    def _get_base_stats_by_type(self, op_type):
        """Возвращает словарь с базовыми характеристиками для типа врага."""
        stats_map = {
            OpponentType.ZOMBIE: {
                'health': 50,
                'agility': 25,
                'strength': 125,
                'hostility': 'AVERAGE',
            },
            OpponentType.VAMPIRE: {
                'health': 50,
                'agility': 75,
                'strength': 125,
                'hostility': 'HIGH',
            },
            OpponentType.GHOST: {
                'health': 75,
                'agility': 75,
                'strength': 25,
                'hostility': 'LOW',
            },
            OpponentType.OGRE: {
                'health': 150,
                'agility': 25,
                'strength': 100,
                'hostility': 'AVERAGE',
            },
            OpponentType.SNAKE: {
                'health': 100,
                'agility': 100,
                'strength': 30,
                'hostility': 'HIGH',
            }
        }
        return stats_map.get(op_type, {'health': 10, 'agility': 10, 'strength': 10, 'hostility': 'AVERAGE'})

    def is_alive(self):
        """Проверяет, жив ли противник"""
        return self.health > 0

    def take_damage(self, damage):
        """Наносит урон противнику"""
        self.health -= damage
        if self.health < 0:
            self.health = 0

    def can_see_player(self, distance_to_player):
        """Проверяет, находится ли игрок в зоне преследования"""
        hostility_radius_map = {
            'LOW': LOW_HOSTILITY_RADIUS,
            'AVERAGE': AVERAGE_HOSTILITY_RADIUS,
            'HIGH': HIGH_HOSTILITY_RADIUS
        }
        hostility_radius = hostility_radius_map.get(self.hostility, AVERAGE_HOSTILITY_RADIUS)
        return distance_to_player <= hostility_radius

    def start_chasing(self):
        """Начинает преследование игрока"""
        self.is_chasing = True

    def stop_chasing(self):
        """Останавливает преследование игрока"""
        self.is_chasing = False

    def get_visual_representation(self):
        """Возвращает символ и цвет для отображения противника"""
        visual_map = {
            OpponentType.ZOMBIE: (SYM_ZOMBIE, "green"),
            OpponentType.VAMPIRE: (SYM_VAMPIRE, "red"),
            OpponentType.GHOST: (SYM_GHOST, "white"),
            OpponentType.OGRE: (SYM_OGRE, "yellow"),
            OpponentType.SNAKE: (SYM_SNAKE, "white")
        }
        return visual_map.get(self.type, ("?", "white"))

    def _is_walkable(self, x, y, rooms, passages, opponents):
        """Проверяет, можно ли встать на клетку (пол/коридор, не занято другим врагом)"""
        if not (0 <= x < COLS and 0 <= y < ROWS):
            return False
        for room in rooms:
            if room is None:
                continue
            if room.crd.x <= x < room.crd.x + room.width and room.crd.y <= y < room.crd.y + room.height:
                for op in opponents:
                    if op is not self and op.is_alive() and op.crd.x == x and op.crd.y == y:
                        return False
                return True
        for passage in passages:
            px, py, pw, ph = passage
            rx, ry = px + 1, py + 1
            rw, rh = pw - 2, ph - 2
            if rx <= x < rx + rw and ry <= y < ry + rh:
                for op in opponents:
                    if op is not self and op.is_alive() and op.crd.x == x and op.crd.y == y:
                        return False
                return True
        return False

    def _find_path_step(self, target_crd, rooms, passages, opponents):
        """BFS: возвращает (dx, dy) первого шага к цели или None если путь не найден"""
        from collections import deque
        sx, sy = self.crd.x, self.crd.y
        tx, ty = target_crd.x, target_crd.y
        if sx == tx and sy == ty:
            return None
        queue = deque([(sx, sy, None)])
        visited = {(sx, sy)}
        DIRS = [(0, -1), (0, 1), (-1, 0), (1, 0)]
        while queue:
            cx, cy, first_step = queue.popleft()
            for dx, dy in DIRS:
                nx, ny = cx + dx, cy + dy
                step = first_step if first_step is not None else (dx, dy)
                if nx == tx and ny == ty:
                    return step
                if (nx, ny) not in visited and self._is_walkable(nx, ny, rooms, passages, opponents):
                    visited.add((nx, ny))
                    queue.append((nx, ny, step))
        return None

    def _pattern_zombie(self, rooms, passages, opponents):
        """Случайное движение в одном из 4 направлений"""
        dirs = [(0, -1), (0, 1), (-1, 0), (1, 0)]
        random.shuffle(dirs)
        for dx, dy in dirs:
            if self._is_walkable(self.crd.x + dx, self.crd.y + dy, rooms, passages, opponents):
                return (dx, dy)
        return None

    def _pattern_vampire(self, rooms, passages, opponents):
        """Случайное движение в одном из 8 направлений"""
        dirs = [(0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (-1, 1), (1, -1), (1, 1)]
        random.shuffle(dirs)
        for dx, dy in dirs:
            if self._is_walkable(self.crd.x + dx, self.crd.y + dy, rooms, passages, opponents):
                return (dx, dy)
        return None

    def _pattern_ghost(self, rooms, passages, opponents):
        """Телепорт в случайную свободную клетку внутри текущей комнаты"""
        current_room = None
        for room in rooms:
            if room is None:
                continue
            if (room.crd.x <= self.crd.x < room.crd.x + room.width and
                    room.crd.y <= self.crd.y < room.crd.y + room.height):
                current_room = room
                break
        if current_room is None:
            return None
        for _ in range(16):
            nx = current_room.crd.x + random.randint(0, current_room.width - 1)
            ny = current_room.crd.y + random.randint(0, current_room.height - 1)
            if self._is_walkable(nx, ny, rooms, passages, opponents):
                return (nx - self.crd.x, ny - self.crd.y)
        return None

    def _pattern_ogre(self, rooms, passages, opponents):
        """Движение на 2 клетки в одном направлении"""
        dirs = [(0, -1), (0, 1), (-1, 0), (1, 0)]
        random.shuffle(dirs)
        for dx, dy in dirs:
            nx1, ny1 = self.crd.x + dx, self.crd.y + dy
            nx2, ny2 = self.crd.x + dx * OGRE_STEP, self.crd.y + dy * OGRE_STEP
            if (self._is_walkable(nx1, ny1, rooms, passages, opponents) and
                    self._is_walkable(nx2, ny2, rooms, passages, opponents)):
                return (dx * OGRE_STEP, dy * OGRE_STEP)
        return None

    def _pattern_snake(self, rooms, passages, opponents):
        """Диагональное движение, не повторяет предыдущее направление"""
        dirs = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
        random.shuffle(dirs)
        for dx, dy in dirs:
            if (dx, dy) == self.last_direction:
                continue
            if self._is_walkable(self.crd.x + dx, self.crd.y + dy, rooms, passages, opponents):
                self.last_direction = (dx, dy)
                return (dx, dy)
        if self.last_direction:
            dx, dy = self.last_direction
            if self._is_walkable(self.crd.x + dx, self.crd.y + dy, rooms, passages, opponents):
                return (dx, dy)
        return None

    def move(self, player_crd, rooms, passages, all_opponents):
        """Двигает противника: преследует игрока или ходит по паттерну"""
        dist = abs(self.crd.x - player_crd.x) + abs(self.crd.y - player_crd.y)

        step = None
        if self.can_see_player(dist):
            self.start_chasing()
            step = self._find_path_step(player_crd, rooms, passages, all_opponents)

        if step is None:
            if self.is_chasing and dist > HIGH_HOSTILITY_RADIUS * 2:
                self.stop_chasing()
            pattern_map = {
                OpponentType.ZOMBIE: self._pattern_zombie,
                OpponentType.VAMPIRE: self._pattern_vampire,
                OpponentType.GHOST: self._pattern_ghost,
                OpponentType.OGRE: self._pattern_ogre,
                OpponentType.SNAKE: self._pattern_snake,
            }
            pattern_fn = pattern_map.get(self.type)
            if pattern_fn:
                step = pattern_fn(rooms, passages, all_opponents)

        if step:
            self.crd.x += step[0]
            self.crd.y += step[1]
            if step[0]:
                self.facing = 1 if step[0] > 0 else -1

class ItemType(Enum):
    """Основные категории предметов."""

    TREASURE = "treasure"
    FOOD = "food"
    ELIXIR = "elixir"
    SCROLL = "scroll"
    WEAPON = "weapon"

class ItemSubType(Enum):
    """Подтипы эликсиров и свитков — какую характеристику они меняют."""

    STRENGTH_ELIXIR = "strength_elixir"
    AGILITY_ELIXIR = "agility_elixir"
    HEALTH_ELIXIR = "health_elixir"

    STRENGTH_SCROLL = "strength_scroll"
    AGILITY_SCROLL = "agility_scroll"
    HEALTH_SCROLL = "health_scroll"

class Subject:
    """Предмет: еда, эликсир, свиток, оружие или сокровище."""

    def __init__(
        self,
        subject_type=None,
        sub_type=None,
        health_effect=0,
        max_health_effect=0,
        agility_effect=0,
        strength_effect=0,
        cost=0,
        name='',
        crd=None
    ):
        """Создаёт предмет с заданными типом и характеристиками (по умолчанию — пустой)."""
        self.type = subject_type
        self.sub_type = sub_type
        self.health_effect = health_effect
        self.max_health_effect = max_health_effect
        self.agility_effect = agility_effect
        self.strength_effect = strength_effect
        self.cost = cost
        self.name = name
        self.crd = crd if crd is not None else Coord()

    def generate_random_type(self, player=None):
        """Случайно выбирает категорию предмета и заполняет его атрибуты соответствующим генератором."""
        random_type = random.choice([
            ItemType.FOOD, ItemType.ELIXIR, ItemType.SCROLL, ItemType.WEAPON
        ])

        if random_type == ItemType.FOOD:
            self.generate_food(player)
        elif random_type == ItemType.ELIXIR:
            self.generate_elixir(player)
        elif random_type == ItemType.SCROLL:
            self.generate_scroll(player)
        elif random_type == ItemType.WEAPON:
            self.generate_weapon()

    def generate_food(self, player):
        """Превращает предмет в еду со случайным именем и восстановлением здоровья."""
        food_names = [
            "Ration of the Ironclad",
            "Crimson Berry Cluster",
            "Loaf of the Forgotten Baker",
            "Smoked Wyrm Jerky",
            "Golden Apple of Vitality",
            "Hardtack of the Endless March",
            "Spiced Venison Strips",
            "Honeyed Nectar Bread",
            "Dried Mushrooms of the Deep",
        ]

        max_regen = int(player.max_health * 0.20)
        health_restored = random.randint(1, max(max_regen, 1))


        self.name = random.choice(food_names)
        self.type = ItemType.FOOD
        self.sub_type = None
        self.health_effect = health_restored
        self.max_health_effect = 0
        self.agility_effect = 0
        self.strength_effect = 0
        self.cost = 0

    def generate_elixir(self, player):
        """Превращает предмет в эликсир со случайным именем и временным бонусом к характеристике."""
        elixir_names = [
            "Elixir of the Jade Serpent",
            "Potion of the Phantom's Breath",
            "Vial of Crimson Vitality",
            "Draught of the Frozen Star",
            "Elixir of the Shattered Mind",
            "Potion of the Wandering Soul",
            "Vial of Ember Essence",
            "Elixir of the Obsidian Veil",
            "Potion of the Howling Wind",
        ]

        stat_types = ["health", "agility", "strength"]
        chosen_stat = random.choice(stat_types)
        self.name = random.choice(elixir_names)
        if chosen_stat == "health":
            max_increase = int(player.max_health * 0.20)
            effect_amount = random.randint(1, max(max_increase, 1))
            self.type = ItemType.ELIXIR
            self.sub_type = ItemSubType.HEALTH_ELIXIR
            self.health_effect = 0
            self.max_health_effect = effect_amount
            self.agility_effect = 0
            self.strength_effect = 0
            self.cost = 0
        elif chosen_stat == "agility":
            max_increase = int(player.agility * 0.10)
            effect_amount = random.randint(1, max(max_increase, 1))
            self.type = ItemType.ELIXIR
            self.sub_type = ItemSubType.AGILITY_ELIXIR
            self.health_effect = 0
            self.max_health_effect = 0
            self.agility_effect = effect_amount
            self.strength_effect = 0
            self.cost = 0
        else:
            max_increase = int(player.strength * 0.10)
            effect_amount = random.randint(1, max(max_increase, 1))
            self.type = ItemType.ELIXIR
            self.sub_type = ItemSubType.STRENGTH_ELIXIR
            self.health_effect = 0
            self.max_health_effect = 0
            self.agility_effect = 0
            self.strength_effect = effect_amount
            self.cost = 0

    def generate_scroll(self, player):
        """Превращает предмет в свиток со случайным именем и постоянным бонусом к характеристике."""
        scroll_names = [
            "Scroll of Shadowstep",
            "Parchment of Eternal Flame",
            "Manuscript of Forgotten Truths",
            "Scroll of Iron Will",
            "Vellum of the Void",
            "Scroll of Whispers",
            "Tome of the Lost King",
            "Scroll of Unseen Paths",
            "Parchment of Thunderous Roar",
        ]

        stat_types = ["health", "agility", "strength"]
        chosen_stat = random.choice(stat_types)
        self.name = random.choice(scroll_names)
        if chosen_stat == "health":
            max_increase = int(player.max_health * 0.20)
            effect_amount = random.randint(1, max(max_increase, 1))
            self.type = ItemType.SCROLL
            self.sub_type = ItemSubType.HEALTH_SCROLL
            self.health_effect = 0
            self.max_health_effect = effect_amount
            self.agility_effect = 0
            self.strength_effect = 0
            self.cost = 0
        elif chosen_stat == "agility":
            max_increase = int(player.agility * 0.10)
            effect_amount = random.randint(1, max(max_increase, 1))
            self.type = ItemType.SCROLL
            self.sub_type = ItemSubType.AGILITY_SCROLL
            self.health_effect = 0
            self.max_health_effect = 0
            self.agility_effect = effect_amount
            self.strength_effect = 0
            self.cost = 0
        else:
            max_increase = int(player.strength * 0.10)
            effect_amount = random.randint(1, max(max_increase, 1))
            self.type = ItemType.SCROLL
            self.sub_type = ItemSubType.STRENGTH_SCROLL
            self.health_effect = 0
            self.max_health_effect = 0
            self.agility_effect = 0
            self.strength_effect = effect_amount
            self.cost = 0

    def generate_weapon(self):
        """Превращает предмет в оружие со случайным именем и силовым бонусом."""
        weapon_names = [
            "Blade of the Forgotten Dawn",
            "Obsidian Reaver",
            "Fang of the Shadow Wolf",
            "Ironclad Cleaver",
            "Crimson Talon",
            "Thunderstrike Maul",
            "Serpent's Kiss Dagger",
            "Voidrend Sword",
            "Ebonheart Spear",
        ]

        weapon_power = random.randint(30, 50)
        self.name = random.choice(weapon_names)
        self.type = ItemType.WEAPON
        self.sub_type = None
        self.health_effect = 0
        self.max_health_effect = 0
        self.agility_effect = 0
        self.strength_effect = weapon_power
        self.cost = 0

