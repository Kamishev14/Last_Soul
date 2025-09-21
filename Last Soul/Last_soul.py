import math
import pygame
import pytmx
import os
import random
import time

# --- SETTINGS ---
WIDTH, HEIGHT = 1024, 720
FPS = 60
ZOOM = 3
GRAVITY = 0.5
JUMP_STRENGTH = -13
PLAYER_SPEED = 4
SOUL_SPEED = 3
SOUL_DURATION = 4  # seconds

# --- INIT ---
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
clock = pygame.time.Clock()
font_path = "data/fonts/Pixellari.ttf"
font = pygame.font.Font(font_path, 48)        # Main font
small_font = pygame.font.Font(font_path, 24)  # Small font for tips

# --- SOUNDS / MUSIC ---
pygame.mixer.init()
sounds = {
    "mana_1": pygame.mixer.Sound("data/sfx/mana_1.wav") if os.path.exists("data/sfx/mana_1.wav") else None,
    "mana_2": pygame.mixer.Sound("data/sfx/mana_2.wav") if os.path.exists("data/sfx/mana_2.wav") else None,
    "death": pygame.mixer.Sound("data/sfx/death.wav") if os.path.exists("data/sfx/death.wav") else None,
    "enter_soul": pygame.mixer.Sound("data/sfx/enter_soul.wav") if os.path.exists("data/sfx/enter_soul.wav") else None,
    "exit_soul": pygame.mixer.Sound("data/sfx/exit_soul.wav") if os.path.exists("data/sfx/exit_soul.wav") else None
}

music1 = pygame.mixer.Sound("data/music_1.wav") if os.path.exists("data/music_1.wav") else None
music2 = pygame.mixer.Sound("data/music_2.wav") if os.path.exists("data/music_2.wav") else None
if music1:
    music1.play(loops=-1)
if music2:
    music2.play(loops=-1)

# --- PLAYER ---
player_vel_y = 0
on_ground = False
player_radius = 7 * ZOOM
is_soul = False
mana = 1
soul_timer = 0
transforming = False
transform_frame = 0
player_frame = 0
animation_speed = 0.15
player_x, player_y = WIDTH // 2, HEIGHT // 2

# --- LOAD ANIMATIONS ---
def load_animation(folder, scale_factor=2):
    frames = []
    if not os.path.isdir(folder):
        return frames
    for filename in sorted(os.listdir(folder)):
        if filename.endswith(".png"):
            img = pygame.image.load(os.path.join(folder, filename)).convert_alpha()
            img = pygame.transform.scale(img, (player_radius * scale_factor, player_radius * scale_factor))
            frames.append(img)
    return frames

idle_frames = load_animation("data/images/animations/player_idle")
run_frames = load_animation("data/images/animations/player_run")
jump_frames = load_animation("data/images/animations/player_jump")
soul_frames = []
for i in range(9):
    path = f"data/images/animations/player_soul/transformation_{i}.png"
    if os.path.exists(path):
        img = pygame.image.load(path).convert_alpha()
        # scale_by isn't always available depending on pygame version; use scale if necessary
        try:
            img = pygame.transform.scale_by(img, 4)
        except AttributeError:
            img = pygame.transform.scale(img, (img.get_width() * 4, img.get_height() * 4))
        soul_frames.append(img)

# --- LEVEL MANAGEMENT ---
current_level = 1
MAX_LEVEL = 3

def load_level(level_num):
    global tmx_data, player_x, player_y, mana_objects, door_objects, TILE_WIDTH, TILE_HEIGHT
    tmx_data = pytmx.load_pygame(f"data/maps/level_{level_num}.tmx")
    TILE_WIDTH = tmx_data.tilewidth * ZOOM
    TILE_HEIGHT = tmx_data.tileheight * ZOOM

    # spawn point from layer
    player_x, player_y = WIDTH // 2, HEIGHT // 2
    for layer in tmx_data.visible_layers:
        if isinstance(layer, pytmx.TiledObjectGroup) and getattr(layer, "name", "") == "spawn_point":
            for obj in layer:
                # object coordinates in Tiled are in pixels already
                player_x = obj.x * ZOOM
                player_y = obj.y * ZOOM

    mana_objects = []
    door_objects = []
    for layer in tmx_data.visible_layers:
        if isinstance(layer, pytmx.TiledObjectGroup):
            if getattr(layer, "name", "") == "mana":
                for obj in layer:
                    rect = pygame.Rect(obj.x * ZOOM, obj.y * ZOOM, obj.width * ZOOM, obj.height * ZOOM)
                    mana_objects.append(rect)
            elif getattr(layer, "name", "") == "door":
                for obj in layer:
                    rect = pygame.Rect(obj.x * ZOOM, obj.y * ZOOM, obj.width * ZOOM, obj.height * ZOOM)
                    door_objects.append(rect)
    # set globals
    globals()["mana_objects"] = mana_objects
    globals()["door_objects"] = door_objects
    # return spawn pos (player_x/player_y are global anyway)
    return player_x, player_y

# initial load
load_level(current_level)

# --- FUNCTIONS ---
def get_solid_tiles():
    solid = []
    for layer in tmx_data.visible_layers:
        if isinstance(layer, pytmx.TiledTileLayer):
            for x, y, gid in layer:
                tile = tmx_data.get_tile_image_by_gid(gid)
                if tile:
                    props = tmx_data.get_tile_properties_by_gid(gid) or {}
                    if props and props.get("collide"):
                        rect = pygame.Rect(
                            x * tmx_data.tilewidth * ZOOM,
                            y * tmx_data.tileheight * ZOOM,
                            tmx_data.tilewidth * ZOOM,
                            tmx_data.tileheight * ZOOM
                        )
                        solid.append(rect)
    return solid

def advance(loc, angle, distance):
    return [loc[0] + math.cos(angle) * distance, loc[1] + math.sin(angle) * distance]

def render_mana(loc, size=[6, 8], color1=(255, 255, 255), color2=(12, 230, 242)):
    global game_time
    points = []
    for i in range(8):
        points.append(advance(
            loc.copy(),
            game_time / 30 + i / 8 * math.pi * 2,
            math.sin((game_time * math.sqrt(i)) / 20) * size[0] + size[1]
        ))
    pygame.draw.polygon(screen, color1, points)
    pygame.draw.polygon(screen, color2, points, 1)

# --- PROJECTILES (ENEMIES) ---
projectiles = []
projectile_img = pygame.Surface((14, 14), pygame.SRCALPHA)
pygame.draw.circle(projectile_img, (255, 60, 60), (7, 7), 7)

def spawn_projectile(target_x, target_y, min_dist=180, max_dist=260, speed_base=3.0):
    """Spawn a projectile at a random point around (target_x, target_y).
    Projectile velocity is calculated once toward that target position and won't home."""
    angle = random.uniform(0, math.tau)  # spawn direction
    dist = random.uniform(min_dist, max_dist)
    spawn_x = target_x + math.cos(angle) * dist
    spawn_y = target_y + math.sin(angle) * dist

    # calculate velocity toward the player's position at spawn time
    dx = target_x - spawn_x
    dy = target_y - spawn_y
    length = math.hypot(dx, dy) or 1.0
    dx /= length
    dy /= length

    # make them slightly faster and a bit varied
    speed = speed_base * 1.3 * random.uniform(0.9, 1.15)  # ~30% faster
    proj = {
        "pos": [spawn_x, spawn_y],
        "vel": [dx * speed, dy * speed],
        "radius": 5
    }
    projectiles.append(proj)

def update_projectiles(player_rect, camera_x, camera_y):
    """Move projectiles, handle collisions and removal.
       Returns:
           "hit" if a projectile collided with player_rect (no removal here)"""
    world_screen_rect = pygame.Rect(camera_x - 32, camera_y - 32, WIDTH + 64, HEIGHT + 64)  # margin
    for proj in projectiles[:]:
        proj["pos"][0] += proj["vel"][0]
        proj["pos"][1] += proj["vel"][1]

        rect = pygame.Rect(proj["pos"][0] - proj["radius"], proj["pos"][1] - proj["radius"],
                           proj["radius"] * 2, proj["radius"] * 2)

        # collision with player
        if rect.colliderect(player_rect):
            # signal hit to caller
            return "hit", proj

        # remove if far off-screen
        if not world_screen_rect.colliderect(rect):
            try:
                projectiles.remove(proj)
            except ValueError:
                pass
    return None, None

# --- DRAW WAVES ---
def draw_waves(game_time, screen, WIDTH, HEIGHT):
    BORDER_SIZE = 80
    COLOR = (10, 5, 8)
    POINTS = 7

    # top wave
    top_points = [[0, BORDER_SIZE]]
    for i in range(POINTS):
        x = WIDTH / POINTS * (i + 1)
        y = BORDER_SIZE + math.sin((game_time + i * 200) / 20) * 60
        top_points.append([x, y])
    top_points += [[WIDTH, BORDER_SIZE], [WIDTH, 0], [0, 0]]
    surf = pygame.Surface((WIDTH, BORDER_SIZE), pygame.SRCALPHA)
    pygame.draw.polygon(surf, COLOR, top_points)
    screen.blit(surf, (0, 0))

    # bottom wave
    bottom_points = [[0, 0]]
    for i in range(POINTS):
        x = WIDTH / POINTS * (i + 1)
        y = 0 - math.sin((game_time + i * 200) / 20) * 60
        bottom_points.append([x, y])
    bottom_points += [[WIDTH, 0], [WIDTH, BORDER_SIZE], [0, BORDER_SIZE]]
    surf = pygame.Surface((WIDTH, BORDER_SIZE), pygame.SRCALPHA)
    pygame.draw.polygon(surf, COLOR, bottom_points)
    screen.blit(surf, (0, HEIGHT - BORDER_SIZE))

    # left wave
    left_points = [[BORDER_SIZE, 0]]
    for i in range(POINTS):
        y = HEIGHT / POINTS * (i + 1)
        x = BORDER_SIZE + math.sin((game_time + i * 200) / 20) * 60
        left_points.append([x, y])
    left_points += [[BORDER_SIZE, HEIGHT], [0, HEIGHT], [0, 0]]
    surf = pygame.Surface((BORDER_SIZE, HEIGHT), pygame.SRCALPHA)
    pygame.draw.polygon(surf, COLOR, left_points)
    screen.blit(surf, (0, 0))

    # right wave
    right_points = [[0, 0]]
    for i in range(POINTS):
        y = HEIGHT / POINTS * (i + 1)
        x = 0 - math.sin((game_time + i * 200) / 20) * 60
        right_points.append([x, y])
    right_points += [[0, HEIGHT], [BORDER_SIZE, HEIGHT], [BORDER_SIZE, 0]]
    surf = pygame.Surface((BORDER_SIZE, HEIGHT), pygame.SRCALPHA)
    pygame.draw.polygon(surf, COLOR, right_points)
    screen.blit(surf, (WIDTH - BORDER_SIZE, 0))

# --- DRAW MAP ---
def draw_map(camera_x, camera_y):
    for layer in tmx_data.visible_layers:
        if isinstance(layer, pytmx.TiledTileLayer):
            for x, y, gid in layer:
                tile = tmx_data.get_tile_image_by_gid(gid)
                if tile:
                    tile = pygame.transform.scale(
                        tile, (tmx_data.tilewidth * ZOOM, tmx_data.tileheight * ZOOM)
                    )
                    screen.blit(tile, (x * tmx_data.tilewidth * ZOOM - camera_x,
                                       y * tmx_data.tileheight * ZOOM - camera_y))
        elif isinstance(layer, pytmx.TiledObjectGroup):
            if getattr(layer, "name", "") == "mana":
                continue
            for obj in layer:
                if hasattr(obj, "gid") and obj.gid:
                    image = tmx_data.get_tile_image_by_gid(obj.gid)
                    if image:
                        image = pygame.transform.scale(
                            image, (int(obj.width * ZOOM), int(obj.height * ZOOM))
                        )
                        screen.blit(image, (obj.x * ZOOM - camera_x, obj.y * ZOOM - camera_y))

# --- GAME OVER UI state ---
game_over = False
game_over_alpha = 0.0  # 0..255 for overlay fade
GAME_OVER_FADE_SPEED = 200.0  # alpha units per second

def draw_game_over():
    # overlay fade
    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, int(game_over_alpha)))
    screen.blit(overlay, (0, 0))

    # central box
    box_w, box_h = 620, 180
    box_x = (WIDTH - box_w) // 2
    box_y = (HEIGHT - box_h) // 2
    pygame.draw.rect(screen, (20, 20, 30), (box_x, box_y, box_w, box_h), border_radius=10)
    pygame.draw.rect(screen, (60, 10, 10), (box_x+2, box_y+2, box_w-4, box_h-4), 3, border_radius=10)

    # text with pulsing effect
    t = pygame.time.get_ticks() / 1000.0
    pulse = 1.0 + 0.07 * math.sin(t * 4.0)
    title = font.render("GAME OVER", True, (255, 80, 80))
    title = pygame.transform.rotozoom(title, 0, pulse)
    screen.blit(title, (WIDTH//2 - title.get_width()//2, box_y + 20))

    info = small_font.render("You died. Press R to retry or ESC to quit.", True, (220, 220, 220))
    screen.blit(info, (WIDTH//2 - info.get_width()//2, box_y + 80))

    # subtle hint
    hint = small_font.render("Retry reloads the current level and clears projectiles.", True, (160, 160, 160))
    screen.blit(hint, (WIDTH//2 - hint.get_width()//2, box_y + 110))

import math
import pygame
import pytmx
import os
import random
import time

# --- SETTINGS ---
WIDTH, HEIGHT = 1024, 720
FPS = 60
ZOOM = 3
GRAVITY = 0.5
JUMP_STRENGTH = -13
PLAYER_SPEED = 4
SOUL_SPEED = 3
SOUL_DURATION = 4  # seconds

# --- INIT ---
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
clock = pygame.time.Clock()

# --- FONTS / GRADIENT FUNCTION ---
def render_text_gradient(text, font, color_top, color_bottom):
    # render solid surface
    surf = font.render(text, True, (255,255,255))
    surf = surf.convert_alpha()
    width, height = surf.get_size()
    # create gradient
    gradient = pygame.Surface((width, height), pygame.SRCALPHA)
    for y in range(height):
        r = int(color_top[0] + (color_bottom[0]-color_top[0])*y/height)
        g = int(color_top[1] + (color_bottom[1]-color_top[1])*y/height)
        b = int(color_top[2] + (color_bottom[2]-color_top[2])*y/height)
        pygame.draw.line(gradient, (r,g,b), (0,y), (width,y))
    # mask gradient with text
    surf.blit(gradient, (0,0), special_flags=pygame.BLEND_RGBA_MULT)
    return surf

font_path = "data/fonts/Pixellari.ttf"
font = pygame.font.Font(font_path, 48)        # Main font
small_font = pygame.font.Font(font_path, 24)  # Small font for tips


# --- SOUNDS / MUSIC ---
pygame.mixer.init()
sounds = {
    "mana_1": pygame.mixer.Sound("data/sfx/mana_1.wav") if os.path.exists("data/sfx/mana_1.wav") else None,
    "mana_2": pygame.mixer.Sound("data/sfx/mana_2.wav") if os.path.exists("data/sfx/mana_2.wav") else None,
    "death": pygame.mixer.Sound("data/sfx/death.wav") if os.path.exists("data/sfx/death.wav") else None,
    "enter_soul": pygame.mixer.Sound("data/sfx/enter_soul.wav") if os.path.exists("data/sfx/enter_soul.wav") else None,
    "exit_soul": pygame.mixer.Sound("data/sfx/exit_soul.wav") if os.path.exists("data/sfx/exit_soul.wav") else None
}

music1 = pygame.mixer.Sound("data/music_1.wav") if os.path.exists("data/music_1.wav") else None
music2 = pygame.mixer.Sound("data/music_2.wav") if os.path.exists("data/music_2.wav") else None
if music1: music1.play(loops=-1)
if music2: music2.play(loops=-1)

# --- PLAYER ---
player_vel_y = 0
on_ground = False
player_radius = 7 * ZOOM
is_soul = False
mana = 1
soul_timer = 0
transforming = False
transform_frame = 0
player_frame = 0
animation_speed = 0.15
player_x, player_y = WIDTH // 2, HEIGHT // 2

# --- LOAD ANIMATIONS ---
def load_animation(folder, scale_factor=2):
    frames = []
    if not os.path.isdir(folder):
        return frames
    for filename in sorted(os.listdir(folder)):
        if filename.endswith(".png"):
            img = pygame.image.load(os.path.join(folder, filename)).convert_alpha()
            img = pygame.transform.scale(img, (player_radius * scale_factor, player_radius * scale_factor))
            frames.append(img)
    return frames

idle_frames = load_animation("data/images/animations/player_idle")
run_frames = load_animation("data/images/animations/player_run")
jump_frames = load_animation("data/images/animations/player_jump")
soul_frames = []
for i in range(9):
    path = f"data/images/animations/player_soul/transformation_{i}.png"
    if os.path.exists(path):
        img = pygame.image.load(path).convert_alpha()
        try:
            img = pygame.transform.scale_by(img, 4)
        except AttributeError:
            img = pygame.transform.scale(img, (img.get_width()*4, img.get_height()*4))
        soul_frames.append(img)

# --- INITIAL PLAYER FRAME ---
if idle_frames:
    current_frame = idle_frames[0]
else:
    current_frame = pygame.Surface((player_radius*2, player_radius*2), pygame.SRCALPHA)
    pygame.draw.circle(current_frame, (200,200,200),
                       (current_frame.get_width()//2,current_frame.get_height()//2),
                       current_frame.get_width()//2)

# --- LEVEL MANAGEMENT ---
current_level = 1
MAX_LEVEL = 3

def load_level(level_num):
    global tmx_data, player_x, player_y, mana_objects, door_objects, TILE_WIDTH, TILE_HEIGHT
    tmx_data = pytmx.load_pygame(f"data/maps/level_{level_num}.tmx")
    TILE_WIDTH = tmx_data.tilewidth * ZOOM
    TILE_HEIGHT = tmx_data.tileheight * ZOOM

    # spawn point
    player_x, player_y = WIDTH//2, HEIGHT//2
    for layer in tmx_data.visible_layers:
        if isinstance(layer, pytmx.TiledObjectGroup) and getattr(layer, "name","")=="spawn_point":
            for obj in layer:
                player_x = obj.x * ZOOM
                player_y = obj.y * ZOOM

    mana_objects = []
    door_objects = []
    for layer in tmx_data.visible_layers:
        if isinstance(layer, pytmx.TiledObjectGroup):
            if getattr(layer,"name","")=="mana":
                for obj in layer:
                    rect = pygame.Rect(obj.x*ZOOM, obj.y*ZOOM, obj.width*ZOOM, obj.height*ZOOM)
                    mana_objects.append(rect)
            elif getattr(layer,"name","")=="door":
                for obj in layer:
                    rect = pygame.Rect(obj.x*ZOOM, obj.y*ZOOM, obj.width*ZOOM, obj.height*ZOOM)
                    door_objects.append(rect)
    globals()["mana_objects"]=mana_objects
    globals()["door_objects"]=door_objects
    return player_x, player_y

load_level(current_level)

# --- FUNCTIONS ---
def get_solid_tiles():
    solid = []
    for layer in tmx_data.visible_layers:
        if isinstance(layer,pytmx.TiledTileLayer):
            for x,y,gid in layer:
                tile = tmx_data.get_tile_image_by_gid(gid)
                if tile:
                    props = tmx_data.get_tile_properties_by_gid(gid) or {}
                    if props.get("collide"):
                        rect = pygame.Rect(
                            x*tmx_data.tilewidth*ZOOM,
                            y*tmx_data.tileheight*ZOOM,
                            tmx_data.tilewidth*ZOOM,
                            tmx_data.tileheight*ZOOM
                        )
                        solid.append(rect)
    return solid

def advance(loc, angle, distance):
    return [loc[0] + math.cos(angle)*distance, loc[1] + math.sin(angle)*distance]

def render_mana(loc, size=[6,8], color1=(255,255,255), color2=(12,230,242)):
    global game_time
    points=[]
    for i in range(8):
        points.append(advance(
            loc.copy(),
            game_time/30 + i/8*math.pi*2,
            math.sin((game_time*math.sqrt(i))/20)*size[0] + size[1]
        ))
    pygame.draw.polygon(screen,color1,points)
    pygame.draw.polygon(screen,color2,points,1)

# --- PROJECTILES ---
projectiles=[]
projectile_img = pygame.Surface((14,14),pygame.SRCALPHA)
pygame.draw.circle(projectile_img,(255,60,60),(7,7),7)

def spawn_projectile(target_x,target_y,min_dist=180,max_dist=260,speed_base=3.0):
    angle = random.uniform(0,math.tau)
    dist = random.uniform(min_dist,max_dist)
    spawn_x = target_x + math.cos(angle)*dist
    spawn_y = target_y + math.sin(angle)*dist
    dx = target_x - spawn_x
    dy = target_y - spawn_y
    length = math.hypot(dx,dy) or 1
    dx/=length
    dy/=length
    speed = speed_base*1.3*random.uniform(0.9,1.15)
    proj={"pos":[spawn_x,spawn_y],"vel":[dx*speed,dy*speed],"radius":5}
    projectiles.append(proj)

def update_projectiles(player_rect,camera_x,camera_y):
    world_screen_rect = pygame.Rect(camera_x-32,camera_y-32,WIDTH+64,HEIGHT+64)
    for proj in projectiles[:]:
        proj["pos"][0]+=proj["vel"][0]
        proj["pos"][1]+=proj["vel"][1]
        rect = pygame.Rect(proj["pos"][0]-proj["radius"],proj["pos"][1]-proj["radius"],
                           proj["radius"]*2,proj["radius"]*2)
        if rect.colliderect(player_rect):
            return "hit", proj
        if not world_screen_rect.colliderect(rect):
            try: projectiles.remove(proj)
            except ValueError: pass
    return None,None

# --- WAVES ---
def draw_waves(game_time,screen,WIDTH,HEIGHT):
    BORDER_SIZE = 80
    COLOR = (10,5,8)
    POINTS = 7
    # top
    top_points=[[0,BORDER_SIZE]]
    for i in range(POINTS):
        x=WIDTH/POINTS*(i+1)
        y=BORDER_SIZE+math.sin((game_time+i*200)/20)*60
        top_points.append([x,y])
    top_points+=[[WIDTH,BORDER_SIZE],[WIDTH,0],[0,0]]
    surf=pygame.Surface((WIDTH,BORDER_SIZE),pygame.SRCALPHA)
    pygame.draw.polygon(surf,COLOR,top_points)
    screen.blit(surf,(0,0))
    # bottom
    bottom_points=[[0,0]]
    for i in range(POINTS):
        x=WIDTH/POINTS*(i+1)
        y=0-math.sin((game_time+i*200)/20)*60
        bottom_points.append([x,y])
    bottom_points+=[[WIDTH,0],[WIDTH,BORDER_SIZE],[0,BORDER_SIZE]]
    surf=pygame.Surface((WIDTH,BORDER_SIZE),pygame.SRCALPHA)
    pygame.draw.polygon(surf,COLOR,bottom_points)
    screen.blit(surf,(0,HEIGHT-BORDER_SIZE))
    # left
    left_points=[[BORDER_SIZE,0]]
    for i in range(POINTS):
        y=HEIGHT/POINTS*(i+1)
        x=BORDER_SIZE+math.sin((game_time+i*200)/20)*60
        left_points.append([x,y])
    left_points+=[[BORDER_SIZE,HEIGHT],[0,HEIGHT],[0,0]]
    surf=pygame.Surface((BORDER_SIZE,HEIGHT),pygame.SRCALPHA)
    pygame.draw.polygon(surf,COLOR,left_points)
    screen.blit(surf,(0,0))
    # right
    right_points=[[0,0]]
    for i in range(POINTS):
        y=HEIGHT/POINTS*(i+1)
        x=0-math.sin((game_time+i*200)/20)*60
        right_points.append([x,y])
    right_points+=[[0,HEIGHT],[BORDER_SIZE,HEIGHT],[BORDER_SIZE,0]]
    surf=pygame.Surface((BORDER_SIZE,HEIGHT),pygame.SRCALPHA)
    pygame.draw.polygon(surf,COLOR,right_points)
    screen.blit(surf,(WIDTH-BORDER_SIZE,0))

# --- DRAW MAP ---
def draw_map(camera_x,camera_y):
    for layer in tmx_data.visible_layers:
        if isinstance(layer,pytmx.TiledTileLayer):
            for x,y,gid in layer:
                tile = tmx_data.get_tile_image_by_gid(gid)
                if tile:
                    tile = pygame.transform.scale(tile,(tmx_data.tilewidth*ZOOM,tmx_data.tileheight*ZOOM))
                    screen.blit(tile,(x*tmx_data.tilewidth*ZOOM-camera_x,
                                      y*tmx_data.tileheight*ZOOM-camera_y))
        elif isinstance(layer,pytmx.TiledObjectGroup):
            if getattr(layer,"name","")=="mana": continue
            for obj in layer:
                if hasattr(obj,"gid") and obj.gid:
                    image=tmx_data.get_tile_image_by_gid(obj.gid)
                    if image:
                        image=pygame.transform.scale(image,(int(obj.width*ZOOM),int(obj.height*ZOOM)))
                        screen.blit(image,(obj.x*ZOOM-camera_x,obj.y*ZOOM-camera_y))

# --- GAME OVER ---
game_over=False
game_over_alpha=0.0
GAME_OVER_FADE_SPEED=200.0

def draw_game_over():
    overlay=pygame.Surface((WIDTH,HEIGHT),pygame.SRCALPHA)
    overlay.fill((0,0,0,int(game_over_alpha)))
    screen.blit(overlay,(0,0))
    box_w,box_h=620,180
    box_x=(WIDTH-box_w)//2
    box_y=(HEIGHT-box_h)//2
    pygame.draw.rect(screen,(20,20,30),(box_x,box_y,box_w,box_h),border_radius=10)
    pygame.draw.rect(screen,(60,10,10),(box_x+2,box_y+2,box_w-4,box_h-4),3,border_radius=10)
    t=pygame.time.get_ticks()/1000.0
    pulse=1.0+0.07*math.sin(t*4.0)
    title = render_text_gradient("GAME OVER", font, (0,120,255), (180,255,255))
    title = pygame.transform.rotozoom(title,0,pulse)
    screen.blit(title,(WIDTH//2-title.get_width()//2, box_y+20))
    info=small_font.render("You died. Press R to retry or ESC to quit.",True,(220,220,220))
    screen.blit(info,(WIDTH//2-info.get_width()//2, box_y+80))
    hint=small_font.render("Retry reloads the current level and clears projectiles.",True,(160,160,160))
    screen.blit(hint,(WIDTH//2-hint.get_width()//2,box_y+110))

# --- EVENT FLAGS ---
event_start_pause=True
event_after_first_soul=False
first_soul_done=False

# --- GAME LOOP ---
game_time=0
running=True
spawn_timer=0.0
SPAWN_INTERVAL=4.0
MIN_SPAWN_COUNT=6
MAX_SPAWN_COUNT=8

while running:
    dt = clock.tick(FPS)/1000.0
    for event in pygame.event.get():
        if event.type==pygame.QUIT:
            running=False

    keys = pygame.key.get_pressed()

    # --- GAME OVER ---
    if game_over:
        if keys[pygame.K_r]:
            game_over=False
            game_over_alpha=0.0
            load_level(current_level)
            projectiles.clear()
            is_soul=False
            transforming=False
            soul_timer=0
            player_x,player_y = globals().get("player_x",player_x), globals().get("player_y",player_y)
            if music1: music1.play(loops=-1)
            if music2: music2.play(loops=-1)
            continue
        if keys[pygame.K_ESCAPE]:
            running=False
        game_over_alpha=min(255.0, game_over_alpha+GAME_OVER_FADE_SPEED*dt)
        draw_game_over()
        pygame.display.flip()
        continue

    # --- START PAUSE ---
    if event_start_pause:
        dx=dy=0
        player_vel_y=0
        on_ground=False
        camera_x, camera_y = player_x-WIDTH//2, player_y-HEIGHT//2
        screen.fill((70,14,43))
        draw_map(camera_x,camera_y)
        draw_waves(game_time,screen,WIDTH,HEIGHT)
        screen.blit(current_frame,(player_x-camera_x-current_frame.get_width()//2,
                                   player_y-camera_y-current_frame.get_height()//2))
        msg = render_text_gradient("Press DOWN ARROW to transform into your soul", small_font,(0,180,255),(180,255,255))
        screen.blit(msg,(WIDTH//2-msg.get_width()//2, HEIGHT//2-50))
        pygame.display.flip()
        if keys[pygame.K_DOWN] and mana>0:
            transforming=True
            transform_frame=0
            mana-=1
            event_start_pause=False
            first_soul_done=True
            if sounds.get("enter_soul"):
                try: sounds["enter_soul"].play()
                except Exception: pass
        game_time+=1
        continue

    # --- NORMAL INPUT ---
    dx=dy=0
    if not transforming:
        if is_soul:
            if keys[pygame.K_a]: dx-=SOUL_SPEED
            if keys[pygame.K_d]: dx+=SOUL_SPEED
            if keys[pygame.K_w]: dy-=SOUL_SPEED
            if keys[pygame.K_s]: dy+=SOUL_SPEED
            if time.time()-soul_timer>SOUL_DURATION:
                is_soul=False
        else:
            if keys[pygame.K_a]: dx-=PLAYER_SPEED
            if keys[pygame.K_d]: dx+=PLAYER_SPEED
            if keys[pygame.K_SPACE] and on_ground:
                player_vel_y=JUMP_STRENGTH
                on_ground=False
            player_vel_y+=GRAVITY
            dy=player_vel_y
            if keys[pygame.K_DOWN] and mana>0:
                transforming=True
                transform_frame=0
                mana-=1
                if sounds.get("enter_soul"):
                    try: sounds["enter_soul"].play()
                    except Exception: pass

    # --- COLLISIONS ---
    solid_tiles=get_solid_tiles()
    if is_soul and soul_frames:
        hitbox_width, hitbox_height = soul_frames[0].get_width()//2, soul_frames[0].get_height()//2
    else:
        hitbox_width, hitbox_height = int(player_radius*1.6), int(player_radius*1.8)
    player_rect=pygame.Rect(player_x-hitbox_width//2, player_y-hitbox_height//2, hitbox_width, hitbox_height)

    player_rect.x+=dx
    for tile in solid_tiles:
        if player_rect.colliderect(tile):
            if dx>0: player_rect.right=tile.left
            if dx<0: player_rect.left=tile.right

    player_rect.y+=dy
    on_ground=False
    for tile in solid_tiles:
        if player_rect.colliderect(tile):
            if dy>0:
                player_rect.bottom=tile.top
                if not is_soul: player_vel_y=0
                on_ground=True
            if dy<0:
                player_rect.top=tile.bottom
                if not is_soul: player_vel_y=0

    player_x,player_y=player_rect.centerx, player_rect.centery
    camera_x, camera_y=player_x-WIDTH//2, player_y-HEIGHT//2

    # --- MANA COLLECTION ---
    for mana_rect in list(globals().get("mana_objects",[])):
        if player_rect.colliderect(mana_rect):
            mana+=1
            if sounds.get("mana_1"):
                try: sounds["mana_1"].play()
                except Exception: pass
            if sounds.get("mana_2"):
                try: sounds["mana_2"].play()
                except Exception: pass
            try: globals()["mana_objects"].remove(mana_rect)
            except Exception: pass

    # --- DOOR ---
    for door_rect in list(globals().get("door_objects",[])):
        if player_rect.colliderect(door_rect):
            current_level+=1
            if current_level>MAX_LEVEL:
                print("You won the game!")
                running=False
            else:
                load_level(current_level)

    # --- SPAWN PROJECTILES ---
    spawn_timer+=dt
    if spawn_timer>=SPAWN_INTERVAL:
        spawn_timer=0.0
        count=random.randint(MIN_SPAWN_COUNT,MAX_SPAWN_COUNT)
        for _ in range(count):
            spawn_projectile(player_x,player_y,min_dist=400,max_dist=600,speed_base=2.0)

    # --- UPDATE PROJECTILES ---
    hit_result, hit_proj = update_projectiles(player_rect,camera_x,camera_y)
    if hit_result=="hit":
        if sounds.get("death"):
            try: sounds["death"].play()
            except Exception: pass
        if is_soul:
            is_soul=False
            transforming=False
            soul_timer=0
            projectiles.clear()
            if sounds.get("exit_soul"):
                try: sounds["exit_soul"].play()
                except Exception: pass
        else:
            game_over=True
            game_over_alpha=0.0
            projectiles.clear()

    # --- TRANSFORMATION ---
    if transforming:
        if soul_frames and int(transform_frame)<len(soul_frames):
            current_frame=soul_frames[int(transform_frame)]
            transform_frame+=0.25
        else:
            transforming=False
            is_soul=True
            soul_timer=time.time()
            current_frame=soul_frames[-1] if soul_frames else pygame.Surface((player_radius,player_radius))
            if sounds.get("enter_soul"):
                try: sounds["enter_soul"].play()
                except Exception: pass
            if first_soul_done and not event_after_first_soul:
                event_after_first_soul=True
                tip_start_time=time.time()
    elif is_soul:
        current_frame=soul_frames[-1] if soul_frames else pygame.Surface((player_radius,player_radius))
    else:
        if not on_ground: frames=jump_frames
        elif dx!=0: frames=run_frames
        else: frames=idle_frames
        if frames:
            player_frame=(player_frame+animation_speed)%len(frames) if len(frames)>1 else 0
            current_frame=frames[int(player_frame)]
        else:
            current_frame=pygame.Surface((player_radius*2,player_radius*2),pygame.SRCALPHA)
            pygame.draw.circle(current_frame,(200,200,200),(current_frame.get_width()//2,current_frame.get_height()//2),current_frame.get_width()//2)
    if dx<0 and not transforming and not is_soul:
        current_frame=pygame.transform.flip(current_frame,True,False)

    # --- DRAW ---
    screen.fill((70,14,43))
    draw_map(camera_x,camera_y)
    draw_waves(game_time,screen,WIDTH,HEIGHT)
    for mana_rect in globals().get("mana_objects",[]):
        render_mana([mana_rect.centerx-camera_x,mana_rect.centery-camera_y])
    for proj in projectiles:
        sx,sy=proj["pos"][0]-camera_x,proj["pos"][1]-camera_y
        screen.blit(projectile_img,(sx-proj["radius"],sy-proj["radius"]))
    screen.blit(current_frame,(player_x-camera_x-current_frame.get_width()//2,
                               player_y-camera_y-current_frame.get_height()//2))
    # HUD
    mana_text = render_text_gradient(f"Mana: {mana}", font,(0,180,255),(180,255,255))
    screen.blit(mana_text,(20,20))

    # --- TIP AFTER FIRST SOUL ---
    if event_after_first_soul and time.time()-tip_start_time<3.0:
        tip_msg = render_text_gradient("You are now a soul! Move freely with WASD.",small_font,(0,180,255),(180,255,255))
        screen.blit(tip_msg,(WIDTH//2-tip_msg.get_width()//2,100))

    pygame.display.flip()
    game_time+=1

pygame.quit()
