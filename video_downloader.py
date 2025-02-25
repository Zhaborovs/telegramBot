import os
import asyncio
from telethon import events
import re
from datetime import datetime

class VideoDownloader:
    def __init__(self, table_manager, config, client=None, bot=None):
        self.table_manager = table_manager
        self.base_path = config.get('downloads_path', 'downloaded_videos')
        self.retry_attempts = int(config.get('retry_attempts', '3'))
        self.download_path = "downloaded_videos"
        self.last_download_success = False
        self.last_saved_filepath = None
        self.current_download = None
        self.client = client
        self.bot = bot
        
        # Создаем папку для видео, если её нет
        if not os.path.exists(self.download_path):
            os.makedirs(self.download_path)
        
    def sanitize_filename(self, filename):
        # Удаляем недопустимые символы из имени файла
        return re.sub(r'[<>:"/\\|?*]', '_', filename)
    
    def get_first_5_words(self, text):
        # Получаем первые 5 слов из текста
        words = text.split()[:5]
        return '_'.join(words)
    
    def get_video_filename(self, prompt_id, model):
        """Генерирует имя файла"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        model_name = model.split()[0].replace('🌙', '').replace('➕', '').replace('📦', '')\
                    .replace('🎬', '').replace('🎯', '').replace('👁', '')\
                    .replace('🌫', '').replace('🦋', '').strip()
        return f"{timestamp}_{prompt_id}_{model_name}.mp4"
    
    async def download_video(self, message, prompt_id, model):
        try:
            self.current_download = prompt_id
            filename = self.get_video_filename(prompt_id, model)
            filepath = os.path.join(self.base_path, filename)
            
            print(f"Начинаю скачивание видео: {filename}")
            await message.download_media(filepath)
            await asyncio.sleep(2)
            
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                print(f"Видео успешно сохранено: {filepath}")
                self.table_manager.mark_completed(prompt_id, model, filepath)
                return True
            else:
                print("Ошибка: файл не был создан или пустой")
                self.table_manager.mark_error(prompt_id, model)
                return False
                
        except Exception as e:
            print(f"Ошибка при скачивании видео: {e}")
            self.table_manager.mark_error(prompt_id, model)
            return False
        finally:
            self.current_download = None

    async def start_monitoring(self):
        @self.client.on(events.NewMessage(from_users=self.bot))
        async def handler(event):
            # Проверяем, есть ли видео в сообщении
            if event.message.media and hasattr(event.message.media, 'document'):
                document = event.message.media.document
                if document.mime_type.startswith('video/'):
                    if self.current_prompt and self.current_model:
                        filename = self.get_video_filename(self.current_prompt, self.current_model)
                        filepath = os.path.join(self.download_path, filename)
                        
                        print(f"Начинаю скачивание видео: {filename}")
                        await self.client.download_media(event.message, filepath)
                        print(f"Видео сохранено: {filepath}")
                        
                        # Сбрасываем промпт и модель после скачивания
                        self.current_prompt = None
                        self.current_model = None
    
    def set_current_prompt(self, prompt, model):
        self.current_prompt = prompt
        self.current_model = model 