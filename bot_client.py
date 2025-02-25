from telethon import TelegramClient, events
import asyncio
import json
import re
from datetime import datetime
import hashlib
from init_config import ConfigInitializer

# Загружаем конфигурацию
config = ConfigInitializer.load_config()
if not config:
    print("Ошибка загрузки конфигурации")
    exit(1)

# Инициализируем клиента
session_name = f"bot_session_{config['api_id']}"
client = TelegramClient(session_name, int(config['api_id']), config['api_hash'])

# Целевой бот для взаимодействия
TARGET_BOT = config.get('bot_name', '@syntxaibot')

class PromptTracker:
    def __init__(self):
        self.last_prompt = None
        self.prompt_history = set()
        self.current_video_prompt = None
        self.pending_downloads = {}  # {message_id: prompt}

    def is_duplicate(self, prompt):
        # Проверяем, не является ли промпт дубликатом последнего
        if prompt == self.last_prompt:
            return True
        
        # Создаем хеш промпта для сравнения
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()
        if prompt_hash in self.prompt_history:
            return True
            
        self.last_prompt = prompt
        self.prompt_history.add(prompt_hash)
        return False

    def set_current_video_prompt(self, prompt, message_id):
        self.current_video_prompt = prompt
        self.pending_downloads[message_id] = prompt

    def get_prompt_for_video(self, message_id):
        return self.pending_downloads.get(message_id)

    def clear_download(self, message_id):
        if message_id in self.pending_downloads:
            del self.pending_downloads[message_id]

prompt_tracker = PromptTracker()

@client.on(events.NewMessage(from_users=TARGET_BOT))
async def handle_bot_messages(event):
    global request_success
    message_text = event.message.text
    
    # Проверяем, содержит ли сообщение информацию о промпте
    if "📍 Ваш запрос:" in message_text:
        prompt = re.search(r'📍 Ваш запрос:\s*(.+)', message_text).group(1)
        prompt_tracker.set_current_video_prompt(prompt, event.message.id)
    
    # Если сообщение содержит видео
    if event.message.video:
        prompt = prompt_tracker.get_prompt_for_video(event.message.id)
        if prompt:
            # Создаем безопасное имя файла из промпта
            safe_filename = "".join(x for x in prompt if x.isalnum() or x in (' ', '-', '_'))[:100]
            filename = f"{safe_filename}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            
            try:
                await client.download_media(event.message, file=f"downloads/{filename}")
                print(f"✅ Видео сохранено как: {filename}")
                prompt_tracker.clear_download(event.message.id)
            except Exception as e:
                print(f"❌ Ошибка при сохранении видео: {e}")

async def send_prompt(prompt):
    if prompt_tracker.is_duplicate(prompt):
        print("⚠️ Обнаружен дубликат промпта, пропускаем...")
        return False
    
    try:
        await client.send_message(TARGET_BOT, prompt)
        print(f"✅ Отправлен промпт: {prompt}")
        return True
    except Exception as e:
        print(f"❌ Ошибка при отправке промпта: {e}")
        return False

async def main():
    await client.start(phone=config['phone_number'])
    
    while True:
        command = input("Введите команду (/video, или 'q' для выхода): ")
        
        if command.lower() == 'q':
            break
            
        if command == '/video':
            await client.send_message(TARGET_BOT, '/video')
            await asyncio.sleep(2)
            await client.send_message(TARGET_BOT, 'sora')
            await asyncio.sleep(2)
            
            prompt = input("Введите промпт: ")
            if await send_prompt(prompt):
                print("⏳ Ожидание генерации видео...")
            else:
                print("❌ Промпт не был отправлен") 