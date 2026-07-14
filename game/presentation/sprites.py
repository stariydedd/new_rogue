from pathlib import Path

import pygame

from presentation.config import TILE_SIZE

ASSETS_DIR = Path(__file__).parent.parent / "assets"
CUSTOM_DIR = ASSETS_DIR / "custom"

# Роли-тайлы масштабируются ровно в клетку (TILE_SIZE), чтобы не было щелей в сетке.
TILE_ROLES = {"floor", "wall", "portal", "path"}


def parse_custom_name(stem):
    """Разбирает имя файла спрайта в (роль, число кадров).

    `player` -> ("player", 1); `player.4` -> ("player", 4) — 4 кадра
    анимации, лежащие в PNG горизонтально слева направо.
    """
    parts = stem.split(".")
    if len(parts) >= 2 and parts[-1].isdigit():
        return ".".join(parts[:-1]), int(parts[-1])
    return stem, 1


class SpriteStore:
    """Раздаёт кадры по ролям из PNG-файлов assets/custom/.

    Вся графика игры — собственные и фанатские спрайты в custom/; атласов нет.
    Файл `<роль>.png` — статичный спрайт, `<роль>.N.png` — N кадров анимации.
    """

    def __init__(self, scale=1):
        self.scale = scale
        self.custom = self._load_custom()
        self._flipped = {}  # кэш зеркальных кадров: роль -> [Surface, ...]

    def _load_custom(self):
        """Загружает спрайты из assets/custom/*.png (если папка есть)."""
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

    def sprite(self, role, tick=0, flip=False):
        """Возвращает кадр роли; tick перебирает кадры анимации по кругу.

        flip=True — кадр, отражённый по горизонтали (персонаж смотрит влево);
        зеркальные кадры считаются один раз и кэшируются."""
        frames = self.custom[role]
        if flip:
            mirrored = self._flipped.get(role)
            if mirrored is None:
                mirrored = [pygame.transform.flip(f, True, False) for f in frames]
                self._flipped[role] = mirrored
            frames = mirrored
        return frames[tick % len(frames)]

    def has_custom(self, role):
        """True, если для роли есть спрайт в assets/custom/."""
        return role in self.custom
