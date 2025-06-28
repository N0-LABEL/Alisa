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
recent_joins = {}  # user_id: last_hour_announcement


@bot.event
async def on_ready():
    print(f"Бот {bot.user} запущен.")
    check_voice_connection.start()
    reset_announcement_tracker.start()


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
        print(f"[{now.strftime('%H:%M')}] Сброс озвучек за час.")


@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    if after.channel and after.channel.id == VOICE_CHANNEL_ID and before.channel != after.channel:
        if any(role.id in ALLOWED_ROLE_IDS for role in member.roles):
            now = datetime.now()
            last_hour = recent_joins.get(member.id)

            if last_hour != now.hour:
                recent_joins[member.id] = now.hour
                display_name = clean_nickname(member.display_name)
                if display_name:
                    await play_tts(f"К нам присоединился участник {display_name}")
                else:
                    print("Невозможно озвучить ник: пустой после фильтрации.")
            else:
                print(f"Пропуск озвучки: {member.display_name} уже был в этом часу.")


def clean_nickname(nick):
    """Удаляет все символы, кроме букв и пробелов."""
    words = re.findall(r"[А-Яа-яA-Za-z]+", nick)
    return " ".join(words)


async def play_tts(text):
    global vc
    if vc and vc.is_connected():
        try:
            print(f"Озвучивается: {text}")
            communicate = edge_tts.Communicate(text, voice="ru-RU-SvetlanaNeural")  # Или AlenaNeural
            await communicate.save("tts.mp3")

            audio_source = discord.FFmpegPCMAudio("tts.mp3")

            if not vc.is_playing():
                vc.play(audio_source)
                while vc.is_playing():
                    await asyncio.sleep(0.5)

            os.remove("tts.mp3")
        except Exception as e:
            print(f"Ошибка воспроизведения: {e}")

bot.run(TOKEN)
