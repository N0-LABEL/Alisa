import discord
from discord.ext import commands, tasks
import asyncio
import os
from datetime import datetime
import re
import edge_tts

TOKEN = ""
GUILD_ID = 1225075859333845154
VOICE_CHANNEL_ID = 1289694911234310155

ALLOWED_ROLE_IDS = [
    1289911579097436232,
    1225212269541986365,
    1226236176298541196,
    1282740488474067039,
    1287407480045043814
]

intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
vc = None
recent_joins = {}    # user_id: count of join announcements this hour
recent_leaves = {}   # user_id: count of leave announcements this hour

tts_queue = asyncio.Queue()
tts_player_task = None

# Карта замен символов на буквы (только символы, цифры не трогаем)
CHAR_MAP = {
    '$': 'S',
    '@': 'a',
    '0': '0',  # цифры оставляем, но для наглядности тут можно убрать
    # Можно расширить, если нужно
}

def clean_nickname(nick):
    """Удаляет символы кроме букв (кириллица и латиница), цифр и пробелов.
    Заменяет отдельные символы на буквы по CHAR_MAP.
    Удаляет остальные символы без склеивания."""
    result = []
    for ch in nick:
        # Проверяем кириллицу, латиницу и цифры
        if re.match(r"[А-Яа-яA-Za-z0-9]", ch):
            result.append(ch)
        elif ch in CHAR_MAP:
            result.append(CHAR_MAP[ch])
        elif ch == ' ':
            result.append(ch)
        else:
            # игнорируем символ без склеивания
            result.append(' ')
    # Убираем лишние пробелы подряд
    text = ''.join(result)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

async def play_tts(text):
    """Внутренняя функция, проигрывает один текст через edge_tts."""
    global vc
    if not vc or not vc.is_connected():
        print("Бот не подключён к голосовому каналу, воспроизведение невозможно.")
        return
    try:
        print(f"Озвучивается: {text}")
        communicate = edge_tts.Communicate(text, voice="ru-RU-SvetlanaNeural")
        await communicate.save("tts.mp3")

        audio_source = discord.FFmpegPCMAudio("tts.mp3")
        vc.play(audio_source)

        while vc.is_playing():
            await asyncio.sleep(0.5)

        os.remove("tts.mp3")
    except Exception as e:
        print(f"Ошибка воспроизведения: {e}")

async def tts_player():
    """Фоновый таск, который последовательно берёт из очереди и проигрывает."""
    while True:
        text = await tts_queue.get()
        await play_tts(text)
        tts_queue.task_done()

async def enqueue_tts(text):
    """Добавляет текст в очередь на озвучку."""
    await tts_queue.put(text)

@bot.event
async def on_ready():
    global tts_player_task
    print(f"Бот {bot.user} запущен.")
    check_voice_connection.start()
    reset_announcement_tracker.start()
    if not tts_player_task:
        tts_player_task = asyncio.create_task(tts_player())

@tasks.loop(seconds=10)
async def check_voice_connection():
    global vc
    guild = bot.get_guild(GUILD_ID)
    channel = guild.get_channel(VOICE_CHANNEL_ID)

    if not guild or not channel:
        return

    if not vc or not vc.is_connected() or vc.channel.id != VOICE_CHANNEL_ID:
        try:
            if vc:
                await vc.disconnect(force=True)
            vc = await channel.connect(reconnect=True)
            print("Бот переподключён к голосовому каналу.")
        except Exception as e:
            print(f"Ошибка подключения: {e}")

@tasks.loop(minutes=1)
async def reset_announcement_tracker():
    now = datetime.now()
    if now.minute == 0:
        recent_joins.clear()
        recent_leaves.clear()
        print(f"[{now.strftime('%H:%M')}] Сброс озвучек за час.")

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    # Пользователь вошёл в нужный канал
    if after.channel and after.channel.id == VOICE_CHANNEL_ID and (not before.channel or before.channel.id != VOICE_CHANNEL_ID):
        if any(role.id in ALLOWED_ROLE_IDS for role in member.roles):
            now = datetime.now()
            count = recent_joins.get(member.id, 0)
            if count < 5:
                recent_joins[member.id] = count + 1
                display_name = clean_nickname(member.display_name)
                if display_name:
                    await enqueue_tts(f"К нам присоединился участник {display_name}")
                else:
                    print("Невозможно озвучить ник: пустой после фильтрации.")
            else:
                print(f"Пропуск озвучки захода: {member.display_name} достиг лимита за час.")

    # Пользователь покинул нужный канал
    if before.channel and before.channel.id == VOICE_CHANNEL_ID and (not after.channel or after.channel.id != VOICE_CHANNEL_ID):
        if any(role.id in ALLOWED_ROLE_IDS for role in member.roles):
            now = datetime.now()
            count = recent_leaves.get(member.id, 0)
            if count < 5:
                recent_leaves[member.id] = count + 1
                display_name = clean_nickname(member.display_name)
                if display_name:
                    await enqueue_tts(f"Участник {display_name} покинул канал")
                else:
                    print("Невозможно озвучить ник: пустой после фильтрации (покинул канал).")
            else:
                print(f"Пропуск озвучки выхода: {member.display_name} достиг лимита за час.")

bot.run(TOKEN)
