GRID_COLS = 5
GRID_STEP = 7.0
BAND_TOP = 14.0
BAND_STEP = 17.0
BAND_LABEL_X = 12.0
BAND_CENTER_X = 50.0
X_MIN, X_MAX = 2.0, 98.0
Y_MIN, Y_MAX = -38.0, 138.0


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def grid_slot(ax, ay, slot):
    col, row = slot % GRID_COLS, slot // GRID_COLS
    return (clamp(ax + (col - (GRID_COLS - 1) / 2) * GRID_STEP, X_MIN, X_MAX),
            clamp(ay + row * GRID_STEP, Y_MIN, Y_MAX))
