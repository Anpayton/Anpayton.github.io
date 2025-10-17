# ascii_doom_radar.py
# ASCII Doom-style shooter with:
# - Room-based random map (open layout)
# - Safe player spawn (never in walls)
# - Head-bob while walking
# - Faster turning, smoother feel
# - Enemy touch damage (HP drains on contact)
# - Enemy occlusion + line-of-sight visibility
# - Rotating minimap radar (top-left corner, follows player)
# Python 3.10+ / Windows Terminal recommended

import os, sys, math, time, msvcrt, random
os.system("")  # enable ANSI

WIDTH, HEIGHT = 100, 32
FOV, DEPTH = math.pi / 3, 16
MOVE_SPEED = 3.0
TURN_SPEED = 4.5
BULLET_SPEED, BULLET_LIFE = 8.0, 2.0
DAMAGE_RATE = 5
BOB_SPEED = 6.0
BOB_INTENSITY = 1.0

# -------------------------------------------------------------------
#  ROOM-BASED WORLD GENERATOR
# -------------------------------------------------------------------
def generate_rooms(width_cells=60, height_cells=35,
                   room_attempts=25, room_min=4, room_max=10):
    grid = [["#"] * width_cells for _ in range(height_cells)]
    rooms = []

    def carve_room(x1, y1, x2, y2):
        for y in range(y1, y2):
            for x in range(x1, x2):
                if 0 <= x < width_cells and 0 <= y < height_cells:
                    grid[y][x] = " "

    for _ in range(room_attempts):
        w = random.randint(room_min, room_max)
        h = random.randint(room_min, room_max)
        x = random.randint(1, width_cells - w - 2)
        y = random.randint(1, height_cells - h - 2)
        new_room = (x, y, x + w, y + h)
        overlap = any(not (x + w + 1 < rx1 or x - 1 > rx2 or
                           y + h + 1 < ry1 or y - 1 > ry2)
                      for rx1, ry1, rx2, ry2 in rooms)
        if not overlap:
            carve_room(x, y, x + w, y + h)
            rooms.append(new_room)

    for i in range(1, len(rooms)):
        cx1 = (rooms[i - 1][0] + rooms[i - 1][2]) // 2
        cy1 = (rooms[i - 1][1] + rooms[i - 1][3]) // 2
        cx2 = (rooms[i][0] + rooms[i][2]) // 2
        cy2 = (rooms[i][1] + rooms[i][3]) // 2
        if random.random() < 0.5:
            carve_room(min(cx1, cx2), cy1, max(cx1, cx2) + 1, cy1 + 1)
            carve_room(cx2, min(cy1, cy2), cx2 + 1, max(cy1, cy2) + 1)
        else:
            carve_room(cx1, min(cy1, cy2), cx1 + 1, max(cy1, cy2) + 1)
            carve_room(min(cx1, cx2), cy2, max(cx1, cx2) + 1, cy2 + 1)

    for x in range(width_cells):
        grid[0][x] = grid[-1][x] = "#"
    for y in range(height_cells):
        grid[y][0] = grid[y][-1] = "#"
    return ["".join(row) for row in grid]


MAP = generate_rooms(60, 35)
MAP_W, MAP_H = len(MAP[0]), len(MAP)

# -------------------------------------------------------------------
#  HELPERS
# -------------------------------------------------------------------
WALL_MAIN = "█▓▒░·"
WALL_CORNER = "╬╩╦╣╠╔╗╝╚"
FLOOR_GRAD = "._-~=:"  # ground pattern

def tile(x, y):
    if 0 <= x < MAP_W and 0 <= y < MAP_H:
        return MAP[int(y)][int(x)]
    return "#"

def is_open(x, y, r=1):
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if tile(x + dx, y + dy) != " ":
                return False
    return True

def safe_spawn():
    candidates = [(x, y) for y in range(1, MAP_H - 1)
                  for x in range(1, MAP_W - 1)
                  if tile(x, y) == " " and is_open(x, y)]
    if not candidates:
        return 2.5, 2.5
    cx, cy = MAP_W / 2, MAP_H / 2
    candidates.sort(key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
    x, y = candidates[0]
    return x + 0.5, y + 0.5

def nearest_open(px, py, maxr=6):
    if tile(px, py) == " ":
        return px, py
    for r in range(1, maxr):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                nx, ny = int(px) + dx, int(py) + dy
                if 0 <= nx < MAP_W and 0 <= ny < MAP_H and tile(nx, ny) == " ":
                    return nx + 0.5, ny + 0.5
    return px, py

def read_key():
    if not msvcrt.kbhit(): return None
    ch = msvcrt.getch()
    if ch in (b'\x00', b'\xe0'):
        code = msvcrt.getch()
        return {b'K':'A', b'M':'D', b'H':'W', b'P':'S'}.get(code, None)
    try:
        c = ch.decode().lower()
        return c.upper()
    except: return None

def rotate_point(x, y, angle):
    # Rotate clockwise (so forward = up on radar)
    ca, sa = math.cos(angle), math.sin(angle)
    rx = x * ca + y * sa
    ry = -x * sa + y * ca
    return rx, ry


# -------------------------------------------------------------------
#  ENTITIES
# -------------------------------------------------------------------
px, py = safe_spawn()
pa = 0.0

class Bullet:
    def __init__(self, x, y, a):
        self.x, self.y, self.a = x, y, a
        self.life = BULLET_LIFE
    def update(self, dt):
        self.x += math.sin(self.a) * BULLET_SPEED * dt
        self.y += math.cos(self.a) * BULLET_SPEED * dt
        self.life -= dt
    def alive(self): return self.life > 0 and tile(self.x, self.y) == " "

class Enemy:
    SPRITE = ["⣿⣿", "⣿⣿"]
    def __init__(self, x, y): self.x, self.y, self.alive = x, y, True
    def update(self, dt):
        if not self.alive: return
        dx, dy = px - self.x, py - self.y
        d = math.hypot(dx, dy)
        if 1 < d < 8:
            self.x += dx / d * dt
            self.y += dy / d * dt
            if tile(self.x, self.y) == "#":
                self.x -= dx / d * dt
                self.y -= dy / d * dt

def spawn_enemies(n=7):
    es = []
    while len(es) < n:
        ex, ey = random.uniform(1, MAP_W - 2), random.uniform(1, MAP_H - 2)
        if tile(ex, ey) == " " and math.hypot(ex - px, ey - py) > 6 and is_open(int(ex), int(ey)):
            es.append(Enemy(ex, ey))
    return es

# -------------------------------------------------------------------
#  RENDERING
# -------------------------------------------------------------------
def render(enemies, bullets, bob):
    zbuffer = [DEPTH] * WIDTH
    frame = [[" "] * WIDTH for _ in range(HEIGHT)]

    for x in range(WIDTH):
        ray = (pa - FOV / 2) + (x / WIDTH) * FOV
        sx, sy = math.sin(ray), math.cos(ray)
        dist, hit = 0.0, False
        while not hit and dist < DEPTH:
            dist += 0.05
            tx, ty = px + sx * dist, py + sy * dist
            if tile(tx, ty) == "#":
                hit = True
        zbuffer[x] = dist
        ceiling = int(HEIGHT / 2 - HEIGHT / dist + bob)
        floor = HEIGHT - ceiling
        shade = WALL_MAIN[min(int(dist / DEPTH * (len(WALL_MAIN) - 1)), len(WALL_MAIN) - 1)]
        gx, gy = int(px + sx * dist), int(py + sy * dist)
        neigh = sum(tile(gx + dx, gy + dy) == "#" for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)])
        if neigh <= 2: shade = random.choice(WALL_CORNER)
        for y in range(HEIGHT):
            if y <= ceiling: frame[y][x] = " "
            elif y <= floor: frame[y][x] = shade
            else:
                t = (y - HEIGHT/2) / (HEIGHT/2)
                idx = min(int(t * (len(FLOOR_GRAD)-1)), len(FLOOR_GRAD)-1)
                frame[y][x] = FLOOR_GRAD[idx]

    # Enemies (line-of-sight + occlusion)
    for e in enemies:
        if not e.alive: continue
        ex, ey = e.x - px, e.y - py
        dist = math.hypot(ex, ey)
        if dist <= 1e-6 or dist >= DEPTH: continue
        # line of sight check (no walls between)
        step = 0.2
        blocked = False
        for d in [i * step for i in range(int(dist / step))]:
            tx = px + math.sin(pa + math.atan2(ex, ey) - pa) * d
            ty = py + math.cos(pa + math.atan2(ex, ey) - pa) * d
            if tile(tx, ty) == "#":
                blocked = True
                break
        if blocked: continue

        angle = math.atan2(ex, ey) - pa
        if abs(angle) >= FOV / 2: continue
        size = max(2, int(HEIGHT / dist))
        mid = int((0.5 + (angle / (FOV / 2)) * 0.5) * WIDTH)
        if zbuffer[mid] < dist: continue
        for sy, row in enumerate(e.SPRITE):
            for sx, ch in enumerate(row):
                for yy in range(size // 2):
                    for xx in range(size // 2):
                        xi = mid + sx * size // 2 + xx - size // 2
                        yi = HEIGHT // 2 + sy * size // 2 + yy - size // 2 + bob
                        if 0 <= xi < WIDTH and 0 <= yi < HEIGHT:
                            frame[yi][xi] = ch

    # Bullets
    for b in bullets:
        bx, by = b.x - px, b.y - py
        dist = math.hypot(bx, by)
        if dist <= 1e-6 or dist > DEPTH: continue
        angle = math.atan2(bx, by) - pa
        if abs(angle) >= FOV / 2: continue
        sxcol = int((0.5 + (angle / (FOV / 2)) * 0.5) * WIDTH)
        syrow = int(HEIGHT / 2 + bob)
        if dist < zbuffer[sxcol] and 0 <= sxcol < WIDTH:
            frame[syrow][sxcol] = "·"

    # Gun sprite
    gun = ["   ║█║   ", "══╣█╠══", "   ║█║   "]
    for i, row in enumerate(gun):
        y = HEIGHT - len(gun) + i
        start = (WIDTH - len(row)) // 2
        for j, ch in enumerate(row):
            frame[y][start + j] = ch

    return frame

# -------------------------------------------------------------------
#  ROTATING MINIMAP RADAR
# -------------------------------------------------------------------
def draw_minimap(frame, enemies, bullets):
    R = 7  # radius in tiles (15×15 map)
    for y in range(-R, R + 1):
        for x in range(-R, R + 1):
            rx, ry = rotate_point(x, y, -pa)
            gx, gy = int(px + rx), int(py + ry)
            if 0 <= gx < MAP_W and 0 <= gy < MAP_H:
                ch = MAP[gy][gx]
                sym = "█" if ch == "#" else " "
                sx, sy = x + R + 2, y + R + 2
                if 0 <= sy < HEIGHT and 0 <= sx < WIDTH:
                    frame[sy][sx] = sym
    for e in enemies:
        if not e.alive: continue
        dx, dy = e.x - px, e.y - py
        dx, dy = rotate_point(dx, dy, -pa)
        mx, my = int(dx + R + 2), int(dy + R + 2)
        if 0 <= mx < 2 * R + 4 and 0 <= my < 2 * R + 4:
            frame[my][mx] = "E"
    for b in bullets:
        dx, dy = b.x - px, b.y - py
        dx, dy = rotate_point(dx, dy, -pa)
        mx, my = int(dx + R + 2), int(dy + R + 2)
        if 0 <= mx < 2 * R + 4 and 0 <= my < 2 * R + 4:
            frame[my][mx] = "·"
    # Player indicator (forward arrow)
    frame[R + 2][R + 2] = "▲"

# -------------------------------------------------------------------
#  MAIN LOOP
# -------------------------------------------------------------------
def main():
    global px, py, pa
    sys.stdout.write("\x1b[2J"); sys.stdout.write("\x1b[?25l")
    enemies, bullets = spawn_enemies(), []
    kills, show_map = 0, True
    last = time.perf_counter()
    health = 100.0
    bob_phase = 0.0

    try:
        while health > 0:
            now = time.perf_counter(); dt = now - last; last = now
            key = read_key()
            moving = False
            if tile(px, py) != " ": px, py = nearest_open(px, py)

            if key == "Q": break
            if key == "A": pa -= TURN_SPEED * dt
            if key == "D": pa += TURN_SPEED * dt
            if key == "W":
                nx, ny = px + math.sin(pa) * MOVE_SPEED * dt, py + math.cos(pa) * MOVE_SPEED * dt
                if tile(nx, ny) == " ":
                    px, py = nx, ny
                    moving = True
            if key == " ": bullets.append(Bullet(px, py, pa))
            if key == "M": show_map = not show_map

            if moving: bob_phase += dt * BOB_SPEED
            else: bob_phase *= 0.9
            bob_pix = int(round(math.sin(bob_phase) * BOB_INTENSITY))

            for b in bullets: b.update(dt)
            bullets = [b for b in bullets if b.alive()]
            for e in enemies:
                e.update(dt)
                for b in bullets:
                    if e.alive and math.hypot(e.x - b.x, e.y - b.y) < 0.5:
                        e.alive = False; b.life = 0; kills += 1
                if e.alive and math.hypot(e.x - px, e.y - py) < 1.0:
                    health -= DAMAGE_RATE * dt

            frame = render(enemies, bullets, bob_pix)
            if show_map: draw_minimap(frame, enemies, bullets)

            sys.stdout.write("\x1b[H")
            print("\n".join("".join(r) for r in frame))
            print(f"HP:{int(health)}  Kills:{kills}  Enemies:{sum(e.alive for e in enemies)}  [W/A/D move | SPACE shoot | M map | Q quit]")
            time.sleep(0.02)

        sys.stdout.write("\x1b[H")
        print("\n" * 10 + " " * 35 + "☠ YOU DIED ☠")
        print(" " * 31 + f"Kills: {kills}")
        time.sleep(2)
    finally:
        sys.stdout.write("\x1b[?25h"); sys.stdout.flush()

if __name__ == "__main__":
    main()
