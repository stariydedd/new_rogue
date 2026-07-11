from pathlib import Path

import pygame

from presentation.config import TILE_SIZE

ASSETS_DIR = Path(__file__).parent.parent / "assets"
CUSTOM_DIR = ASSETS_DIR / "custom"

# Семантические роли -> спрайт по умолчанию из атласа 0x72.
# Свой PNG в assets/custom/<role>.png переопределяет роль, не трогая остальное.
ROLE_DEFAULTS = {
    "player": "knight_m_idle_anim",
    "pudge": "zombie_idle_anim",
    "bloodseeker": "ice_zombie_idle_anim",
    "ghost": "necromancer_idle_anim",
    "axe": "ogre_idle_anim",
    "skywrath": "lizard_f_idle_anim",
    "food": "flask_red",
    "elixir": "flask_blue",
    "scroll": "flask_yellow",
    "sword": "weapon_regular_sword",
    "coin": "coin_anim",
    "wall": "wall_mid",
    "ladder": "floor_ladder",
    "floor": "floor_1",
    "path": "floor_1",  # пол коридоров; без кастомного PNG совпадает с полом
}

# Роли-тайлы масштабируются ровно в клетку (TILE_SIZE), чтобы не было щелей в сетке.
TILE_ROLES = {"floor", "wall", "ladder", "path"}


def parse_custom_name(stem):
    """Разбирает имя файла кастомного спрайта в (роль, число кадров).

    `player` -> ("player", 1); `player.4` -> ("player", 4) — 4 кадра
    анимации, лежащие в PNG горизонтально слева направо.
    """
    parts = stem.split(".")
    if len(parts) >= 2 and parts[-1].isdigit():
        return ".".join(parts[:-1]), int(parts[-1])
    return stem, 1


class SpriteStore:
    """Загружает атлас 0x72 DungeonTilesetII и раздаёт кадры по имени/роли.

    Формат tileset_coords.txt: `name x y w h frames` — кадры анимации лежат
    в атласе горизонтально с шагом w. Пользовательские PNG из assets/custom/
    переопределяют роли из ROLE_DEFAULTS.
    """

    def __init__(self, scale):
        self.scale = scale
        sheet = pygame.image.load(str(ASSETS_DIR / "tileset.png")).convert_alpha()
        self.frames = {}
        for line in (ASSETS_DIR / "tileset_coords.txt").read_text().splitlines():
            parts = line.split()
            if len(parts) < 6:
                continue
            name = parts[0]
            x, y, w, h, count = map(int, parts[1:6])
            frames = []
            for i in range(count):
                rect = pygame.Rect(x + i * w, y, w, h)
                if rect.right > sheet.get_width() or rect.bottom > sheet.get_height():
                    continue
                frame = sheet.subsurface(rect)
                frame = pygame.transform.scale(frame, (w * scale, h * scale))
                frames.append(frame)
            if frames:
                self.frames[name] = frames

        self.custom = self._load_custom()
        self._flipped = {}  # кэш зеркальных кадров: ключ -> [Surface, ...]

    def _load_custom(self):
        """Загружает переопределения из assets/custom/*.png (если папка есть)."""
        custom = {}
        if not CUSTOM_DIR.is_dir():
            return custom
        for png in sorted(CUSTOM_DIR.glob("*.png")):
            role, count = parse_custom_name(png.stem)
            img = pygame.image.load(str(png)).convert_alpha()
            frame_w = img.get_width() // max(count, 1)
            frame_h = img.get_height()
            frames = []
            for i in range(count):
                fr = img.subsurface(pygame.Rect(i * frame_w, 0, frame_w, frame_h))
                if role in TILE_ROLES:
                    fr = pygame.transform.scale(fr, (TILE_SIZE, TILE_SIZE))
                frames.append(fr)
            if frames:
                custom[role] = frames
        return custom

    def frame(self, name, tick=0):
        """Возвращает кадр атласа по имени; tick перебирает кадры по кругу."""
        frames = self.frames[name]
        return frames[tick % len(frames)]

    def sprite(self, role, tick=0, flip=False):
        """Возвращает кадр роли: сперва пользовательский PNG, иначе спрайт из атласа.

        Неизвестная роль трактуется как прямое имя атласа (напр. 'floor_3').
        flip=True — кадр, отражённый по горизонтали (персонаж смотрит влево);
        зеркальные кадры считаются один раз и кэшируются."""
        if role in self.custom:
            key, frames = ("custom", role), self.custom[role]
        else:
            name = ROLE_DEFAULTS.get(role, role)
            key, frames = ("atlas", name), self.frames[name]
        if flip:
            mirrored = self._flipped.get(key)
            if mirrored is None:
                mirrored = [pygame.transform.flip(f, True, False) for f in frames]
                self._flipped[key] = mirrored
            frames = mirrored
        return frames[tick % len(frames)]

    def has_custom(self, role):
        """True, если для роли есть пользовательский спрайт в assets/custom/."""
        return role in self.custom

    def has(self, name):
        return name in self.frames
