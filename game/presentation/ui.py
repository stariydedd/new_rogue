import pygame
from domain.businessLogic import build_grid_map, compute_visibility, item_stat_label
from domain.consts import (
    COLS,
    PLAYER_NAME,
    ROWS,
    SYM_CORRIDOR,
    SYM_DOOR,
    SYM_EMPTY,
    SYM_EXIT,
    SYM_ITEM,
    SYM_PLAYER,
    SYM_ROOM_FLOOR,
    SYM_WALL,
)
from domain.domain import ItemType, OpponentType

# Размеры экрана и видимой области читаются через модуль: в тач-режиме
# apply_touch_layout меняет их на портретную раскладку уже после импорта.
from presentation import config as cfg
from presentation.colors import (
    BLACK,
    GOLD,
    HILITE,
    HINT_COLOR,
    MSG_COLOR,
    PANEL_BG,
    WHITE,
)
from presentation.config import (
    ANIM_FRAME_MS,
    MAP_H,
    MAP_W,
    TILE_SIZE,
)

# Клетки, под которыми рисуется пол: сетка отмечает предметы и игрока
# отдельными символами, но визуально это те же клетки пола.
FLOOR_SYMBOLS = (SYM_ROOM_FLOOR, SYM_CORRIDOR, SYM_DOOR, SYM_EXIT, SYM_ITEM, SYM_PLAYER)

# Значения — семантические роли: каждой соответствует PNG в assets/custom/.
OPPONENT_SPRITES = {
    OpponentType.ZOMBIE: "pudge",
    OpponentType.VAMPIRE: "bloodseeker",
    OpponentType.GHOST: "riki",
    OpponentType.OGRE: "axe",
    OpponentType.SNAKE: "skywrath",
}

# Сокровища не появляются на карте (золото начисляется за убийство),
# поэтому спрайта для ItemType.TREASURE нет.
ITEM_SPRITES = {
    ItemType.FOOD: "food",
    ItemType.ELIXIR: "elixir",
    ItemType.SCROLL: "scroll",
    ItemType.WEAPON: "sword",
}

PLAYER_SPRITE = "player"

# Затемнение исследованных, но невидимых сейчас клеток.
EXPLORED_DIM_ALPHA = 175


def _blit(screen, font, text, pos, color):
    """Рисует одну строку текста в заданной точке (левый верхний угол)."""
    screen.blit(font.render(text, True, color), pos)


def _center_text(screen, font, text, y, color):
    """Рисует строку текста, отцентрированную по ширине экрана."""
    surf = font.render(text, True, color)
    rect = surf.get_rect(centerx=cfg.SCREEN_W // 2, y=y)
    screen.blit(surf, rect)


def _dim_background(screen):
    """Затемняет игровое поле полупрозрачным слоем (для диалогов поверх карты)."""
    overlay = pygame.Surface((cfg.SCREEN_W, cfg.SCREEN_H), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 160))
    screen.blit(overlay, (0, 0))


def _anim_tick():
    return pygame.time.get_ticks() // ANIM_FRAME_MS


def _camera_offset(player):
    """Смещение камеры в пикселях: центр на игроке, с прижатием к краям карты."""
    px = player.crd.x * TILE_SIZE + TILE_SIZE // 2
    py = player.crd.y * TILE_SIZE + TILE_SIZE // 2
    cam_x = max(0, min(MAP_W - cfg.GRID_W, px - cfg.GRID_W // 2))
    cam_y = max(0, min(MAP_H - cfg.GRID_H, py - cfg.GRID_H // 2))
    return cam_x, cam_y


def _visible_cell_range(cam_x, cam_y):
    """Диапазон клеток карты, попадающих в кадр (с запасом в 1 тайл)."""
    x0 = max(0, cam_x // TILE_SIZE - 1)
    y0 = max(0, cam_y // TILE_SIZE - 1)
    x1 = min(COLS, (cam_x + cfg.GRID_W) // TILE_SIZE + 2)
    y1 = min(ROWS, (cam_y + cfg.GRID_H) // TILE_SIZE + 2)
    return x0, y0, x1, y1


def _cell_hash(x, y):
    """Детерминированный, но хорошо перемешанный хеш клетки.

    Линейная формула вида x*7+y*13 даёт строго периодичные узоры вдоль рядов
    (деревья «через каждые N клеток»); битовое перемешивание убирает
    периодичность, сохраняя стабильность между кадрами."""
    h = x * 374761393 + y * 668265263
    h = (h ^ (h >> 13)) * 1274126177
    return (h ^ (h >> 16)) & 0x7FFFFFFF


def _path_cells(passages, rooms):
    """Клетки троп: коридоры (и двери) за вычетом пола комнат.

    Сетка символов затирает клетку игрока/предмета маркером, поэтому тип
    земли под ними по ней не определить — считаем тропы из данных уровня."""
    cells = set()
    for px, py, pw, ph in passages:
        for yy in range(py + 1, py + ph - 1):
            for xx in range(px + 1, px + pw - 1):
                cells.add((xx, yy))
    for room in rooms:
        if room is None:
            continue
        for yy in range(room.crd.y, room.crd.y + room.height):
            for xx in range(room.crd.x, room.crd.x + room.width):
                cells.discard((xx, yy))
    return cells


def _blit_tile(screen, sprites, role, x, y, cam_x, cam_y, tick=0):
    """Рисует спрайт клетки (x, y) с учётом камеры, якорь — верхний левый угол тайла."""
    screen.blit(sprites.sprite(role, tick), (x * TILE_SIZE - cam_x, y * TILE_SIZE - cam_y))


def _blit_entity(screen, sprites, role, x, y, cam_x, cam_y, tick=0, flip=False):
    """Рисует персонажа с якорем по низу клетки: высокие спрайты возвышаются над тайлом."""
    frame = sprites.sprite(role, tick, flip)
    rect = frame.get_rect()
    rect.midbottom = (x * TILE_SIZE + TILE_SIZE // 2 - cam_x, (y + 1) * TILE_SIZE - cam_y)
    screen.blit(frame, rect)


def draw_map(screen, fonts, sprites, session):
    """Отрисовывает уровень: тайлы, предметы, персонажей и туман войны с камерой."""
    rooms = session.get_rooms()
    passages = session.get_passages()
    player = session.get_player()
    level_exit = session.get_exit()
    opponents = session.get_opponents()
    visible_opponents = [op for op in opponents if op.is_alive() and op.is_visible]

    base_grid = build_grid_map(rooms, passages, player, level_exit)
    fully_visible, wall_only = compute_visibility(session, base_grid)

    cam_x, cam_y = _camera_offset(player)
    x0, y0, x1, y1 = _visible_cell_range(cam_x, cam_y)
    tick = _anim_tick()
    path_cells = _path_cells(passages, rooms)

    screen.fill(BLACK, (0, 0, cfg.GRID_W, cfg.GRID_H))

    dim = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
    dim.fill((0, 0, 0, EXPLORED_DIM_ALPHA))

    trees = []  # (x, y, hash) — деревья рисуются после тайлов, чтобы кроны не резались

    for y in range(y0, y1):
        for x in range(x0, x1):
            cell = base_grid[y][x]
            visible = (x, y) in fully_visible
            explored = (x, y) in wall_only
            # Для тайлов карты кадры кастомного PNG — пространственные варианты:
            # выбираются детерминированным хешем клетки, а не временем.
            cell_hash = _cell_hash(x, y)
            if cell == SYM_EMPTY or (not visible and not explored):
                # Пустота и неисследованное — сплошная чаща: карта выглядит как
                # поляны, прорубленные в лесу, а туман войны — как тёмный лес.
                _blit_tile(screen, sprites, "wall", x, y, cam_x, cam_y, cell_hash)
                if not visible:
                    screen.blit(dim, (x * TILE_SIZE - cam_x, y * TILE_SIZE - cam_y))
                elif sprites.has_custom("tree") and cell_hash % 5 == 0:
                    trees.append((x, y, cell_hash))
                continue
            if cell in FLOOR_SYMBOLS:
                # Тропы определяются по данным уровня (не по символу клетки —
                # его затирают маркеры игрока/предметов); остальной пол — "floor".
                base_role = "path" if (x, y) in path_cells else "floor"
                _blit_tile(screen, sprites, base_role, x, y, cam_x, cam_y, cell_hash)
                if cell == SYM_EXIT:
                    _blit_tile(screen, sprites, "portal", x, y, cam_x, cam_y)
                elif (cell == SYM_ROOM_FLOOR and visible
                        and sprites.has_custom("decor") and cell_hash % 11 == 0):
                    # Редкие кустики оживляют поляны.
                    _blit_tile(screen, sprites, "decor", x, y, cam_x, cam_y, cell_hash // 11)
            elif cell == SYM_WALL:
                _blit_tile(screen, sprites, "wall", x, y, cam_x, cam_y, cell_hash)
                if visible and sprites.has_custom("tree") and cell_hash % 4 == 0:
                    trees.append((x, y, cell_hash))
            if not visible:
                screen.blit(dim, (x * TILE_SIZE - cam_x, y * TILE_SIZE - cam_y))

    for x, y, cell_hash in trees:
        _blit_entity(screen, sprites, "tree", x, y, cam_x, cam_y, cell_hash)

    for room in rooms:
        if room is None:
            continue
        for item in room.items:
            if (item.crd.x, item.crd.y) in fully_visible:
                role = ITEM_SPRITES.get(item.type, "food")
                _blit_tile(screen, sprites, role, item.crd.x, item.crd.y, cam_x, cam_y, tick)

    for opponent in visible_opponents:
        if (opponent.crd.x, opponent.crd.y) not in fully_visible:
            continue
        role = OPPONENT_SPRITES.get(opponent.type, "pudge")
        _blit_entity(screen, sprites, role, opponent.crd.x, opponent.crd.y, cam_x, cam_y, tick,
                     flip=opponent.facing < 0)

    _blit_entity(screen, sprites, PLAYER_SPRITE, player.crd.x, player.crd.y, cam_x, cam_y, tick,
                 flip=player.facing < 0)


def draw_status_panel(screen, fonts, sprites, session):
    """Нижняя панель: портрет, HP-бар, характеристики, сообщение, подсказки.

    Вёрстка тремя фиксированными рядами (имя / HP / статы) с общим левым краем;
    портрет живёт в слоте постоянной ширины, чтобы размеры кадров анимации
    не сдвигали остальные элементы."""
    player = session.get_player()
    pygame.draw.rect(screen, PANEL_BG, (0, cfg.GRID_H, cfg.SCREEN_W, cfg.PANEL_H))
    if cfg.TOUCH_MODE:
        _draw_status_panel_touch(screen, fonts, sprites, session, player)
        return

    slot_w = 56
    portrait = sprites.sprite(PLAYER_SPRITE, _anim_tick())
    screen.blit(portrait, portrait.get_rect(center=(12 + slot_w // 2, cfg.GRID_H + cfg.PANEL_H // 2)))

    text_x = 12 + slot_w + 14
    _blit(screen, fonts.ui, PLAYER_NAME, (text_x, cfg.GRID_H + 8), GOLD)

    # Ряд HP: сердечко и цифры выровнены по вертикальному центру бара.
    bar_y = cfg.GRID_H + 34
    bar_h = 16
    heart = pygame.transform.scale(sprites.sprite("heart"), (18, 18))
    screen.blit(heart, (text_x, bar_y - 1))
    bar_x = text_x + 26
    bar_w = 200
    ratio = player.health / player.max_health if player.max_health else 0
    ratio = max(0.0, min(1.0, ratio))
    pygame.draw.rect(screen, (60, 20, 20), (bar_x, bar_y, bar_w, bar_h))
    pygame.draw.rect(screen, (205, 52, 48), (bar_x, bar_y, int(bar_w * ratio), bar_h))
    pygame.draw.rect(screen, (18, 6, 6), (bar_x, bar_y, bar_w, bar_h), 2)
    _blit(screen, fonts.small, f"{player.health}/{player.max_health}",
          (bar_x + bar_w + 10, bar_y + (bar_h - 10) // 2), WHITE)

    weapon_name = f"{player.weapon.name} [+{player.weapon.strength_effect}]" if player.weapon else "Bare hands"
    stats = (
        f"STR {player.strength}   AGI {player.agility}   "
        f"LVL {session.level_num}   GOLD {player.treasures}   WPN {weapon_name}"
    )
    _blit(screen, fonts.ui, stats, (text_x, cfg.GRID_H + 62), WHITE)

    if session.message:
        msg_surf = fonts.ui.render(session.message, True, MSG_COLOR)
        screen.blit(msg_surf, msg_surf.get_rect(topright=(cfg.SCREEN_W - 12, cfg.GRID_H + 10)))
    binds = "[WASD] Move  [F+dir] Run  [H] Weapon  [J] Food  [K] Elixir  [E] Scroll  [F1] Help  [Q] Menu"
    binds_surf = fonts.small.render(binds, True, HINT_COLOR)
    screen.blit(binds_surf, binds_surf.get_rect(bottomright=(cfg.SCREEN_W - 12, cfg.SCREEN_H - 4)))


def _draw_status_panel_touch(screen, fonts, sprites, session, player):
    """Компактная панель для узкого экрана: без подсказок клавиш.

    Ряды: имя + уровень, HP-бар, характеристики + золото, оружие (всегда
    видно), сообщение на двух собственных строках."""
    slot_w = 56
    portrait = sprites.sprite(PLAYER_SPRITE, _anim_tick())
    screen.blit(portrait, portrait.get_rect(center=(12 + slot_w // 2, cfg.GRID_H + cfg.PANEL_H // 2)))
    text_x = 12 + slot_w + 14

    _blit(screen, fonts.ui, PLAYER_NAME, (text_x, cfg.GRID_H + 8), GOLD)
    lvl_surf = fonts.ui.render(f"LVL {session.level_num}", True, GOLD)
    screen.blit(lvl_surf, lvl_surf.get_rect(topright=(cfg.SCREEN_W - 12, cfg.GRID_H + 8)))

    bar_y = cfg.GRID_H + 34
    bar_h = 16
    heart = pygame.transform.scale(sprites.sprite("heart"), (18, 18))
    screen.blit(heart, (text_x, bar_y - 1))
    bar_x = text_x + 26
    bar_w = 180
    ratio = player.health / player.max_health if player.max_health else 0
    ratio = max(0.0, min(1.0, ratio))
    pygame.draw.rect(screen, (60, 20, 20), (bar_x, bar_y, bar_w, bar_h))
    pygame.draw.rect(screen, (205, 52, 48), (bar_x, bar_y, int(bar_w * ratio), bar_h))
    pygame.draw.rect(screen, (18, 6, 6), (bar_x, bar_y, bar_w, bar_h), 2)
    _blit(screen, fonts.small, f"{player.health}/{player.max_health}",
          (bar_x + bar_w + 10, bar_y + (bar_h - 10) // 2), WHITE)

    _blit(screen, fonts.ui, f"STR {player.strength}  AGI {player.agility}", (text_x, cfg.GRID_H + 62), WHITE)
    gold_surf = fonts.ui.render(f"GOLD {player.treasures}", True, WHITE)
    screen.blit(gold_surf, gold_surf.get_rect(topright=(cfg.SCREEN_W - 12, cfg.GRID_H + 62)))

    weapon_name = f"{player.weapon.name} +{player.weapon.strength_effect}" if player.weapon else "Bare hands"
    _blit(screen, fonts.small, f"WPN {weapon_name}", (text_x, cfg.GRID_H + 94), HINT_COLOR)
    if session.message:
        # Строки сообщения ниже портрета — можно начать от левого края панели.
        msg_x = 12
        max_chars = (cfg.SCREEN_W - msg_x - 8) // 10
        for i, line in enumerate(_message_lines(session.message, max_chars)[:2]):
            _blit(screen, fonts.small, line, (msg_x, cfg.GRID_H + 118 + i * 22), MSG_COLOR)


def draw_playing(screen, fonts, sprites, session):
    """Полный кадр игрового процесса: карта + статус-панель."""
    draw_map(screen, fonts, sprites, session)
    draw_status_panel(screen, fonts, sprites, session)


def draw_item_menu_overlay(screen, fonts, items, allow_zero, selected=0):
    """Рисует список предметов поверх нижней части карты.

    Выбор — цифрами или стрелками/крестовиной (подсвеченная строка) + Enter."""
    lines = []
    if allow_zero:
        lines.append("0: Bare hands")
    for i, item in enumerate(items):
        lines.append(f"{i + 1}: {item.name}{item_stat_label(item)}")
    cancel_hint = "MENU: cancel" if cfg.TOUCH_MODE else "ESC: cancel"
    row_h = 34 if cfg.TOUCH_MODE else 22
    # На тач-экране цифровые префиксы бессмысленны (клавиатуры нет), а длинные
    # имена предметов не помещаются ui-шрифтом — компактный шрифт без номеров.
    font = fonts.compact if cfg.TOUCH_MODE else fonts.ui
    if cfg.TOUCH_MODE:
        lines = [line.split(": ", 1)[1] for line in lines]
    glyph_w = font.size("M")[0]
    max_chars = (cfg.SCREEN_W - 24) // glyph_w

    box_h = 10 + (len(lines) + 1) * row_h
    box_y = cfg.GRID_H - box_h
    pygame.draw.rect(screen, (10, 10, 10), (0, box_y, cfg.SCREEN_W, box_h))
    pygame.draw.rect(screen, (90, 90, 90), (0, box_y, cfg.SCREEN_W, box_h), 1)
    for i, line in enumerate(lines):
        prefix = "> " if i == selected else "  "
        color = HILITE if i == selected else WHITE
        _blit(screen, font, (prefix + line)[:max_chars], (10, box_y + 6 + i * row_h), color)
    _blit(screen, font, "  " + cancel_hint, (10, box_y + 6 + len(lines) * row_h), HINT_COLOR)


def _draw_dialog_box(screen, fonts, title, options, selected):
    """Рисует затемнение и центральное диалоговое окно с опциями."""
    _dim_background(screen)
    box_w, box_h = min(520, cfg.SCREEN_W - 16), 60 + len(options) * 40
    box_x = (cfg.SCREEN_W - box_w) // 2
    box_y = (cfg.SCREEN_H - box_h) // 2
    pygame.draw.rect(screen, (25, 25, 25), (box_x, box_y, box_w, box_h))
    pygame.draw.rect(screen, GOLD, (box_x, box_y, box_w, box_h), 2)
    _center_text(screen, fonts.ui, title, box_y + 16, WHITE)
    for i, (label, _) in enumerate(options):
        color = HILITE if i == selected else WHITE
        _center_text(screen, fonts.ui, label, box_y + 56 + i * 40, color)


def draw_quit_dialog(screen, fonts, options, selected):
    """Диалог подтверждения возврата в главное меню (текущий забег будет потерян)."""
    _draw_dialog_box(screen, fonts, "Return to menu? Run will be lost.", options, selected)


def _menu_backdrop(screen, sprites):
    """Фон экранов меню — сплошной чёрный."""
    screen.fill(BLACK)


def _title_with_shadow(screen, fonts, text, y):
    shadow = fonts.title.render(text, True, (60, 40, 0))
    surf = fonts.title.render(text, True, GOLD)
    rect = surf.get_rect(centerx=cfg.SCREEN_W // 2, y=y)
    screen.blit(shadow, rect.move(4, 4))
    screen.blit(surf, rect)


def draw_main_menu(screen, fonts, sprites, options, selected, message=""):
    """Главное меню: фон из тайлов, герой и выбор опций с маркером-мечом."""
    _menu_backdrop(screen, sprites)
    _title_with_shadow(screen, fonts, "YurneROGUE", 118)
    _center_text(screen, fonts.small, "Every strike may be the last.", 178, HINT_COLOR)

    hero = pygame.transform.scale_by(sprites.sprite(PLAYER_SPRITE, _anim_tick()), 3)
    screen.blit(hero, hero.get_rect(centerx=cfg.SCREEN_W // 2, y=210))

    menu_y = 360
    for i, (label, _) in enumerate(options):
        color = HILITE if i == selected else WHITE
        surf = fonts.menu.render(label, True, color)
        screen.blit(surf, surf.get_rect(centerx=cfg.SCREEN_W // 2, y=menu_y + i * 52))

    if message:
        _center_text(screen, fonts.ui, message, cfg.SCREEN_H - 60, MSG_COLOR)
    hint = "D-pad + SELECT" if cfg.TOUCH_MODE else "WASD / arrows + Enter"
    _center_text(screen, fonts.small, hint, cfg.SCREEN_H - 28, HINT_COLOR)


def draw_leaderboard_screen(screen, fonts, sprites, records, source=""):
    """Экран таблицы рекордов. records=None — глобальный топ ещё грузится."""
    _menu_backdrop(screen, sprites)
    _title_with_shadow(screen, fonts, "HIGH SCORES", 40)
    if source:
        _center_text(screen, fonts.small, source, 110, HINT_COLOR)
    # На узком экране полная таблица не помещается — остаются ключевые колонки.
    narrow = cfg.SCREEN_W < 900
    if narrow:
        header = f"{'#':>3} {'NAME':<16} {'GOLD':>6} {'LVL':>4}"
    else:
        header = (
            f"{'#':>3} {'NAME':<16} {'GOLD':>6} {'LVL':>4} {'KILLS':>5} {'FOOD':>4} "
            f"{'ELIX':>4} {'SCRL':>4} {'ATK':>5} {'HIT':>5} {'MOVE':>6}"
        )
    if records is None:
        _center_text(screen, fonts.ui, "Loading global leaderboard...", 170, WHITE)
    elif not records:
        _center_text(screen, fonts.ui, "No records yet.", 170, WHITE)
    else:
        _center_text(screen, fonts.small, header, 150, (170, 170, 170))
        for i, r in enumerate(records):
            name = str(r.get("player_name", "-"))[:16]
            if narrow:
                line = f"{i + 1:>3} {name:<16} {r['treasures']:>6} {r['level']:>4}"
            else:
                line = (
                    f"{i + 1:>3} {name:<16} {r['treasures']:>6} {r['level']:>4} {r['enemies_killed']:>5} "
                    f"{r['food_used']:>4} {r['elixirs_used']:>4} {r['scrolls_read']:>4} "
                    f"{r['attacks_made']:>5} {r['hits_taken']:>5} {r['tiles_moved']:>6}"
                )
            color = HILITE if i == 0 else WHITE
            _center_text(screen, fonts.small, line, 180 + i * 28, color)
    hint = "Any button to return..." if cfg.TOUCH_MODE else "Press any key to return..."
    _center_text(screen, fonts.small, hint, cfg.SCREEN_H - 32, HINT_COLOR)


def draw_name_entry(screen, fonts, sprites, name_input):
    """Экран ввода имени игрока перед новой игрой."""
    _menu_backdrop(screen, sprites)
    _title_with_shadow(screen, fonts, "YOUR NAME", 170)
    hero = pygame.transform.scale_by(sprites.sprite(PLAYER_SPRITE, _anim_tick()), 3)
    screen.blit(hero, hero.get_rect(centerx=cfg.SCREEN_W // 2, y=260))
    box_w, box_h = min(460, cfg.SCREEN_W - 24), 48
    box_x = (cfg.SCREEN_W - box_w) // 2
    box_y = 420
    pygame.draw.rect(screen, (25, 25, 25), (box_x, box_y, box_w, box_h))
    pygame.draw.rect(screen, GOLD, (box_x, box_y, box_w, box_h), 2)
    _blit(screen, fonts.menu, name_input + "_", (box_x + 14, box_y + 14), WHITE)
    hint = ("SELECT: begin   MENU: back" if cfg.TOUCH_MODE
            else "Enter: start   Esc: back   (empty = anonymous)")
    _center_text(screen, fonts.small, hint, box_y + box_h + 26, HINT_COLOR)


HELP_ENEMIES = [
    ("pudge", "Pudge", "Tough and slow. Wanders randomly."),
    ("bloodseeker", "Bloodseeker", "Steals your max HP. Deflects your first strike."),
    ("riki", "Riki", "Blinks around the room, mostly invisible."),
    ("axe", "Axe", "Moves 2 tiles. Rests, counters, never misses."),
    ("skywrath", "Skywrath Mage", "Moves diagonally. Hits may put you to sleep."),
]

HELP_ITEMS = [
    ("food", "Food", "Restores health."),
    ("elixir", "Elixir", "Temporary stat buff for 20 turns."),
    ("scroll", "Scroll", "Permanent stat buff."),
    ("sword", "Weapon", "Equip it; the old one drops nearby."),
    ("portal", "Exit", "Descend deeper. Clear level 21 to win."),
]


def _help_sprite(sprites, role, slot):
    """Спрайт легенды, вписанный в слот slot x slot."""
    frame = sprites.sprite(role)
    if frame.get_width() > slot or frame.get_height() > slot:
        ratio = min(slot / frame.get_width(), slot / frame.get_height())
        frame = pygame.transform.scale_by(frame, ratio)
    return frame


def _help_row(screen, fonts, sprites, role, name, desc, x, y, slot=52):
    """Строка легенды: спрайт в слоте slot x slot, справа имя и описание."""
    frame = _help_sprite(sprites, role, slot)
    rect = frame.get_rect(center=(x + slot // 2, y + slot // 2))
    screen.blit(frame, rect)
    _blit(screen, fonts.ui, name, (x + slot + 14, y + 6), WHITE)
    _blit(screen, fonts.small, desc, (x + slot + 14, y + 30), HINT_COLOR)


def _wrap_text(text, max_chars):
    """Делит строку на куски не длиннее max_chars по границам слов."""
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _message_lines(message, max_chars):
    """Разбивает сообщение статуса на строки для узкого экрана.

    «Picked up: имя [+3 STR].» ломается по двоеточию — заголовок отдельно,
    предмет отдельно; сообщения без двоеточия переносятся по словам."""
    if len(message) <= max_chars:
        return [message]
    head, sep, tail = message.partition(": ")
    if sep and len(head) + 1 <= max_chars and len(tail) <= max_chars:
        return [head + ":", tail]
    return _wrap_text(message, max_chars)


def _help_row_narrow(screen, fonts, sprites, role, name, desc, x, y, desc_lines, slot=36):
    """Строка легенды для узкого экрана: описание в desc_lines строк с переносом."""
    frame = _help_sprite(sprites, role, slot)
    screen.blit(frame, frame.get_rect(center=(x + slot // 2, y + slot // 2)))
    tx = x + slot + 12
    _blit(screen, fonts.ui, name, (tx, y), WHITE)
    max_chars = (cfg.SCREEN_W - tx - 8) // 10  # ширина строки в глифах small-шрифта
    for i, line in enumerate(_wrap_text(desc, max_chars)[:desc_lines]):
        _blit(screen, fonts.small, line, (tx, y + 18 + i * 13), HINT_COLOR)


def draw_help(screen, fonts, sprites):
    """Экран справки: легенда врагов, предметов и выхода."""
    _menu_backdrop(screen, sprites)
    _title_with_shadow(screen, fonts, "HELP", 24)

    if cfg.SCREEN_W < 900:
        # Узкий экран: одна колонка над панелью кнопок. Врагам — две строки
        # описания, предметам хватает одной (высота панели ограничивает).
        x, y = 20, 82
        _blit(screen, fonts.ui, "ENEMIES", (x, y), GOLD)
        y += 26
        for role, name, desc in HELP_ENEMIES:
            _help_row_narrow(screen, fonts, sprites, role, name, desc, x, y, desc_lines=2)
            y += 50
        y += 8
        _blit(screen, fonts.ui, "ITEMS", (x, y), GOLD)
        y += 26
        for role, name, desc in HELP_ITEMS:
            _help_row_narrow(screen, fonts, sprites, role, name, desc, x, y, desc_lines=1)
            y += 38
    else:
        left_x, right_x = 90, 700
        top_y = 120
        _blit(screen, fonts.ui, "ENEMIES", (left_x, top_y), GOLD)
        for i, (role, name, desc) in enumerate(HELP_ENEMIES):
            _help_row(screen, fonts, sprites, role, name, desc, left_x, top_y + 36 + i * 66)

        _blit(screen, fonts.ui, "ITEMS", (right_x, top_y), GOLD)
        for i, (role, name, desc) in enumerate(HELP_ITEMS):
            _help_row(screen, fonts, sprites, role, name, desc, right_x, top_y + 36 + i * 66)

        binds = "[WASD] Move  [F+dir] Run  [H] Weapon  [J] Food  [K] Elixir  [E] Scroll  [F1] Help  [Q] Menu"
        _center_text(screen, fonts.small, binds, cfg.SCREEN_H - 64, WHITE)

    hint = "Tap to return..." if cfg.TOUCH_MODE else "Press any key to return..."
    _center_text(screen, fonts.small, hint, cfg.SCREEN_H - 32, HINT_COLOR)


def draw_end_screen(screen, fonts, sprites, message, submit_status=""):
    """Экран смерти или победы со статусом отправки результата на сервер."""
    _menu_backdrop(screen, sprites)
    _title_with_shadow(screen, fonts, message, cfg.SCREEN_H // 2 - 80)
    if submit_status:
        # На узком экране длинный статус не помещается ui-шрифтом.
        status_font = fonts.small if cfg.SCREEN_W < 900 else fonts.ui
        _center_text(screen, status_font, submit_status, cfg.SCREEN_H // 2 + 20, MSG_COLOR)
    hint = "Press SELECT to exit." if cfg.TOUCH_MODE else "Press Enter to exit."
    _center_text(screen, fonts.small, hint, cfg.SCREEN_H // 2 + 60, HINT_COLOR)
