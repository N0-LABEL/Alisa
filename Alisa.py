import discord
from discord.ext import commands, tasks
import asyncio
import os
from datetime import datetime
import re
import edge_tts
import json

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
TTS_PERMISSION_ROLES = [
    1225212269541986365,
    1226236176298541196
]

# Путь к файлу с пользовательскими именами
CUSTOM_NAMES_FILE = "custom_names.json"

intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
intents.guilds = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="ya!", intents=intents)
vc = None
recent_joins = {}    # user_id: count of join announcements this hour
recent_leaves = {}   # user_id: count of leave announcements this hour
tts_queue = asyncio.Queue()
tts_player_task = None

# Загрузка пользовательских имен из файла (создает файл, если его нет)
def load_custom_names():
    try:
        with open(CUSTOM_NAMES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        # Создаем пустой файл, если он не существует
        with open(CUSTOM_NAMES_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f, ensure_ascii=False, indent=2)
        return {}
    except json.JSONDecodeError:
        # Если файл поврежден, создаем новый
        with open(CUSTOM_NAMES_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f, ensure_ascii=False, indent=2)
        return {}

# Сохранение пользовательских имен в файл
def save_custom_names(custom_names):
    with open(CUSTOM_NAMES_FILE, 'w', encoding='utf-8') as f:
        json.dump(custom_names, f, ensure_ascii=False, indent=2)

custom_names = load_custom_names()

def clean_nickname(nick):
    """Очищает никнейм от нежелательных символов, оставляя пробелы"""
    # Заменяем нежелательные символы на пробелы, кроме букв, цифр и пробелов
    cleaned = re.sub(r"[^a-zA-Zа-яА-ЯёЁ0-9\s]", " ", nick)
    # Удаляем лишние пробелы
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if cleaned else None

async def play_tts(text):
    """Воспроизводит текст через TTS"""
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
    """Фоновый таск для воспроизведения TTS"""
    while True:
        text = await tts_queue.get()
        await play_tts(text)
        tts_queue.task_done()

async def enqueue_tts(text):
    """Добавляет текст в очередь TTS"""
    await tts_queue.put(text)

@bot.event
async def on_ready():
    global tts_player_task
    print(f"Бот {bot.user} запущен.")

    # Устанавливаем активность бота
    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Activity(
            type=discord.ActivityType.listening,
            name="ya!alisa"
        )
    )

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

@bot.command(name='name')
async def set_custom_name(ctx, *, name: str = None):
    """Устанавливает кастомное имя для озвучки"""
    if ctx.guild:
        await ctx.reply(embed=discord.Embed(
            title="✉️ Личные сообщения",
            description="Пожалуйста, используйте эту команду в личных сообщениях бота.",
            color=0xe74c3c
        ))
        return
    if not name:
        await ctx.send(embed=discord.Embed(
            title="⚠️ Ошибка",
            description="Пожалуйста, укажите имя после команды.",
            color=0xe74c3c
        ))
        return

    # Очищаем имя
    cleaned_name = clean_nickname(name)
    if not cleaned_name:
        await ctx.send(embed=discord.Embed(
            title="⚠️ Ошибка",
            description="Имя содержит только недопустимые символы. Пожалуйста, используйте буквы и цифры.",
            color=0xe74c3c
        ))
        return

    # Сохраняем имя пользователя
    custom_names[str(ctx.author.id)] = cleaned_name
    save_custom_names(custom_names)

    await ctx.send(embed=discord.Embed(
        title="✅ Успешно",
        description=f"Теперь я буду называть вас **{cleaned_name}** при входе в голосовой канал.",
        color=0x2ecc71
    ))

@bot.command(name='say')
async def say_text(ctx, *, text: str = None):
    """Произносит указанный текст в голосовом канале"""
    if ctx.guild:
        await ctx.reply(embed=discord.Embed(
            title="✉️ Личные сообщения",
            description="Пожалуйста, используйте эту команду в личных сообщениях бота.",
            color=0xe74c3c
        ))
        return
    if not text:
        await ctx.send(embed=discord.Embed(
            title="⚠️ Ошибка",
            description="Пожалуйста, укажите текст для озвучки.",
            color=0xe74c3c
        ))
        return

    # Проверяем разрешения
    guild = bot.get_guild(GUILD_ID)
    member = guild.get_member(ctx.author.id)
    if not member or not any(role.id in TTS_PERMISSION_ROLES for role in member.roles):
        await ctx.send(embed=discord.Embed(
            title="⛔ Нет доступа",
            description="У вас нет прав использовать эту команду.",
            color=0xe74c3c
        ))
        return

    # Проверяем длину текста
    if len(text) > 200:
        await ctx.send(embed=discord.Embed(
            title="⚠️ Ошибка",
            description="Текст слишком длинный (максимум 200 символов).",
            color=0xe74c3c
        ))
        return

    await enqueue_tts(text)

    await ctx.send(embed=discord.Embed(
        title="🗣️ Текст в очереди",
        description=f"Текст будет озвучен: \"{text}\"",
        color=0x3498db
    ))

@bot.command(name='alisa')
async def show_help(ctx):
    """Показывает список доступных команд"""
    if ctx.guild:
        await ctx.reply(embed=discord.Embed(
            title="✉️ Личные сообщения",
            description="Пожалуйста, используйте эту команду в личных сообщениях бота.",
            color=0xe74c3c
        ))
        return
    embed = discord.Embed(
        title="📌 Помощь по командам",
        description="Список доступных команд и их описание:",
        color=0x9966CC
    )

    embed.add_field(
        name="ya!name [имя]",
        value="Установить кастомное имя для озвучки при входе/выходе из голосового канала",
        inline=False
    )

    embed.add_field(
        name="ya!say [текст]",
        value="Озвучить произвольный текст (только для граждан)",
        inline=False
    )

    embed.add_field(
        name="ya!alisa",
        value="Показать это сообщение",
        inline=False
    )

    embed.set_footer(text="Голосовой помощник", icon_url=bot.user.avatar.url if bot.user.avatar else None)

    await ctx.send(embed=embed)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    # Получаем имя для озвучки (кастомное или никнейм)
    user_id = str(member.id)
    display_name = custom_names.get(user_id, clean_nickname(member.display_name))

    if not display_name:
        print(f"Невозможно озвучить имя пользователя {member.id}")
        return
    # Пользователь вошёл в нужный канал
    if after.channel and after.channel.id == VOICE_CHANNEL_ID and (not before.channel or before.channel.id != VOICE_CHANNEL_ID):
        if any(role.id in ALLOWED_ROLE_IDS for role in member.roles):
            now = datetime.now()
            count = recent_joins.get(member.id, 0)
            if count < 5:
                recent_joins[member.id] = count + 1
                await enqueue_tts(f"К нам присоединился участник {display_name}")
    # Пользователь покинул нужный канал
    if before.channel and before.channel.id == VOICE_CHANNEL_ID and (not after.channel or after.channel.id != VOICE_CHANNEL_ID):
        if any(role.id in ALLOWED_ROLE_IDS for role in member.roles):
            now = datetime.now()
            count = recent_leaves.get(member.id, 0)
            if count < 5:
                recent_leaves[member.id] = count + 1
                await enqueue_tts(f"Участник {display_name} покинул канал")

bot.run(TOKEN)
