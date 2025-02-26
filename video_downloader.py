import os
import asyncio
from telethon import events
import re
from datetime import datetime

class VideoDownloader:
    def __init__(self, table_manager, config):
        self.table_manager = table_manager
        self.base_path = config.get('downloads_path', 'downloaded_videos')
        self.retry_attempts = int(config.get('retry_attempts', '3'))
        self.download_path = "downloaded_videos"
        self.last_download_success = False
        self.last_saved_filepath = None
        self.current_download = None
        
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
            
    async def download_any_video(self, message, model_name=None):
        """Скачивает видео без привязки к конкретному промпту, обрабатывая все активные запросы"""
        try:
            # Извлекаем текст сообщения для поиска промпта
            message_text = message.text or ''
            
            # Получаем список активных промптов из таблицы
            all_prompts = self.table_manager.get_all_prompts()
            active_prompts = self.table_manager.get_active_prompts()
            prompt_id = None
            model = model_name or 'unknown'
            prompt_text = None
            found_prompt = None
            
            # Ищем промпт в тексте сообщения, сравнивая его с промптами из таблицы
            if message_text:
                # Предположим, что промпт идет после фраз типа "Ваше видео по запросу:" или просто находится в сообщении
                possible_prompt = message_text
                
                # Пытаемся найти совпадение с любым промптом из таблицы
                for table_prompt in all_prompts:
                    table_prompt_text = table_prompt.get('prompt', '')
                    # Проверяем, содержит ли сообщение промпт из таблицы
                    if table_prompt_text and table_prompt_text.lower() in possible_prompt.lower():
                        found_prompt = table_prompt
                        prompt_text = table_prompt_text
                        print(f"Найден промпт в сообщении: '{prompt_text}' (ID: {found_prompt['id']})")
                        break
            
            # Если промпт не найден в сообщении, но есть активные промпты - используем совпадение по модели
            if not found_prompt and active_prompts:
                # Ищем промпт для совпадающей модели
                matching_prompt = None
                for prompt in active_prompts:
                    if model_name and prompt.get('model') == model_name:
                        matching_prompt = prompt
                        break
                
                # Если не нашли совпадающий промпт, берем первый
                found_prompt = matching_prompt or active_prompts[0]
                prompt_text = found_prompt.get('prompt', '')
            
            # Если промпт найден, используем его ID
            if found_prompt:
                prompt_id = found_prompt['id']
                
                # Если модель не задана, используем модель из промпта
                if not model_name:
                    model = found_prompt.get('model', 'unknown')
                
                # Генерируем имя файла на основе промпта
                # Получаем первые 5 слов из промпта для имени файла
                prompt_words = '_'.join(prompt_text.split()[:5])
                # Очищаем от спецсимволов
                prompt_words = ''.join(c if c.isalnum() or c in ['_', '-'] else '_' for c in prompt_words)
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                model_short = model.split()[0].replace('🌙', '').replace('➕', '').replace('📦', '')\
                            .replace('🎬', '').replace('🎯', '').replace('👁', '')\
                            .replace('🌫', '').replace('🦋', '').strip()
                filename = f"{timestamp}_{prompt_id}_{model_short}_{prompt_words}.mp4"
            else:
                # Если промпт не найден, сохраняем с временным именем
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                model_short = model.split()[0].replace('🌙', '').replace('➕', '').replace('📦', '')\
                            .replace('🎬', '').replace('🎯', '').replace('👁', '')\
                            .replace('🌫', '').replace('🦋', '').strip()
                filename = f"unknown_{timestamp}_{model_short}.mp4"
                print(f"Промпт не найден, сохраняем видео как: {filename}")
            
            # Создаем путь к файлу и скачиваем видео
            filepath = os.path.join(self.base_path, filename)
            
            print(f"Скачивание видео для промпта {prompt_id if prompt_id else 'неизвестно'} с моделью {model}: {filename}")
            await message.download_media(filepath)
            
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                print(f"Видео успешно сохранено: {filepath}")
                # Отмечаем промпт как завершенный, если он был найден
                if prompt_id:
                    self.table_manager.mark_completed(prompt_id, model, filepath)
                return True
            else:
                print("Ошибка: файл не был создан или пустой")
                return False
                
        except Exception as e:
            print(f"Ошибка при скачивании видео: {e}")
            return False

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