"""Where an auto-placed thing goes: the numbers and the grid, with no database.

`store/layout.py` lays out a site held in the database and needs SQLAlchemy to
do it. The numbers it places by are plain arithmetic, and code that never opens
a database places things by the same ones. They live here, importing nothing,
so both read one copy.

Positions are percentages of the map: x runs 0-100 across, y runs 0-100 down
and may go a little past either end.
"""

#: A grid of auto-placed places: this many across, this far apart.
GRID_COLS = 5
GRID_STEP = 7.0
#: Zones with no label position are stacked in bands down the map: the first
#: band's y, the distance between bands, and where a band's label and the
#: middle of its places sit across.
BAND_TOP = 14.0
BAND_STEP = 17.0
BAND_LABEL_X = 12.0
BAND_CENTER_X = 50.0
#: How far an auto-placed position may go in each direction.
X_MIN, X_MAX = 2.0, 98.0
Y_MIN, Y_MAX = -38.0, 138.0


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def grid_slot(ax, ay, slot):
    """(x, y) of the `slot`-th place (0-based) gridded under an anchor.

    Rows of GRID_COLS, centred on `ax`, the first row at `ay` and each next one
    GRID_STEP further down. Clamped to the limits above, not rounded.
    """
    col, row = slot % GRID_COLS, slot // GRID_COLS
    return (clamp(ax + (col - (GRID_COLS - 1) / 2) * GRID_STEP, X_MIN, X_MAX),
            clamp(ay + row * GRID_STEP, Y_MIN, Y_MAX))
