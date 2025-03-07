import os
import asyncio
from telethon import events
import re
from datetime import datetime
import hashlib
import gc

class VideoDownloader:
    def __init__(self, table_manager, config, client=None, logger=None):
        self.table_manager = table_manager
        self.config = config
        self.logger = logger
        self.client = client  # Сразу сохраняем client при инициализации
        self.download_path = config.get('downloads_path', 'downloaded_videos')
        self.retry_attempts = int(config.get('retry_attempts', '3'))
        self.last_download_success = False
        self.last_saved_filepath = None
        self.current_download = None
        self.message_monitor = None  # Ссылка на MessageMonitor добавится потом
        
        # Создаем папку для видео, если её нет
        if not os.path.exists(self.download_path):
            os.makedirs(self.download_path)
            if self.logger:
                self.logger.log_app_event("DIRECTORY_CREATED", f"Создана директория для видео: {self.download_path}")
        
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
        """
        Скачивает видео из сообщения
        
        Args:
            message: Сообщение с видео
            prompt_id: ID промпта
            model: Модель генерации
            
        Returns:
            bool: True если успешно, False если ошибка
        """
        try:
            # Генерируем имя файла
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            model_name = model.split()[0].replace('🌙', '').replace('➕', '').replace('📦', '')\
                         .replace('🎬', '').replace('🎯', '').replace('👁', '')\
                         .replace('🌫', '').replace('🦋', '').strip()
                         
            # Получаем статус промпта
            prompt_status = self.table_manager.get_status(prompt_id)
            if prompt_status:
                prompt = prompt_status.get('prompt', '')
                # Берем первые 5 слов из промпта для имени файла
                if prompt:
                    prompt_short = self.get_first_5_words(prompt)
                    prompt_short = self.sanitize_filename(prompt_short)
                else:
                    prompt_short = ""
            else:
                prompt_short = ""
                
            # Формируем имя файла
            file_name = f"{timestamp}_{prompt_id}_{model_name}_{prompt_short}.mp4"
            file_path = os.path.join(self.download_path, file_name)
            
            print(f"ℹ️ Информация о видео: {message.media.document.mime_type}, размер: {message.media.document.size} байт")
            print(f"⏳ Начинаем загрузку видео в файл: {file_path}")
            
            # Получаем клиент для загрузки
            from telethon import TelegramClient
            client = None
            if hasattr(self, 'client') and isinstance(self.client, TelegramClient):
                client = self.client
            elif self.message_monitor and hasattr(self.message_monitor, 'client'):
                client = self.message_monitor.client
                
            # Ожидаем загрузку файла
            await message.download_media(file_path)
            
            print(f"✅ Видео успешно загружено: {file_path}")
            
            if self.logger:
                self.logger.log_video_downloaded(prompt_id, file_path, model, True)
                
            # Отмечаем в таблице
            self.table_manager.mark_completed(prompt_id, model, file_path)
            
            self.last_download_success = True
            self.last_saved_filepath = file_path
            return True
            
        except Exception as e:
            error_message = f"❌ Ошибка при скачивании видео: {str(e)}"
            print(error_message)
            
            if self.logger:
                self.logger.log_video_downloaded(prompt_id, "", model, False, str(e))
                self.logger.log_exception(e, context=f"При скачивании видео для промпта {prompt_id}")
                
            # Отмечаем ошибку в таблице
            self.table_manager.mark_error(prompt_id, model, str(e))
            
            self.last_download_success = False
            return False
    
    def extract_model_from_text(self, message_text):
        """Извлекает имя модели из текста сообщения"""
        if not message_text:
            return None
            
        # Ищем модель в формате "🧮 Модель: #Sora" или "Модель: #Sora"
        model_patterns = [
            r'(?:\*\*)?🧮\s+Модель:(?:\*\*)?\s+`?#?([^`\n]+)`?',
            r'Модель:\s+`?#?([^`\n]+)`?'
        ]
        
        for pattern in model_patterns:
            model_match = re.search(pattern, message_text, re.IGNORECASE)
            if model_match:
                model_text = model_match.group(1).strip()
                # Сопоставляем с известными моделями
                if model_text.lower() == 'sora':
                    return '🌙 SORA'
                elif any(m in model_text.lower() for m in ['hailuo', 'minimax']):
                    return '➕ Hailuo MiniMax'
                elif any(m in model_text.lower() for m in ['runway', 'gen-3']):
                    return '📦 RunWay: Gen-3'
                elif 'kling' in model_text.lower():
                    return '🎬 Kling 1.6'
                elif 'pika' in model_text.lower():
                    return '🎯 Pika 2.0'
                elif any(m in model_text.lower() for m in ['act-one', 'аватары']):
                    return '👁 Act-One (Аватары 2.0)'
                elif 'luma' in model_text.lower():
                    return '🌫 Luma: DM'
                elif 'стилизатор' in model_text.lower():
                    return '🦋 RW: Стилизатор'
                print(f"Извлечена модель из сообщения: {model_text}")
                return model_text
        
        # Если не нашли по паттернам, ищем ключевые слова в сообщении
        message_lower = message_text.lower()
        models_map = {
            'sora': '🌙 SORA',
            'hailuo': '➕ Hailuo MiniMax',
            'minimax': '➕ Hailuo MiniMax',
            'runway': '📦 RunWay: Gen-3',
            'gen-3': '📦 RunWay: Gen-3',
            'kling': '🎬 Kling 1.6',
            'pika': '🎯 Pika 2.0',
            'act-one': '👁 Act-One (Аватары 2.0)',
            'аватары': '👁 Act-One (Аватары 2.0)',
            'luma': '🌫 Luma: DM',
            'стилизатор': '🦋 RW: Стилизатор'
        }
        
        # Ищем упоминания моделей в тексте сообщения
        for key, model in models_map.items():
            if key in message_lower:
                return model
        
        return None
        
    async def download_any_video(self, message):
        """
        Скачивает любое видео без привязки к конкретному промпту
        
        Args:
            message: Сообщение с видео
            
        Returns:
            bool: True если успешно, False если ошибка
        """
        try:
            # Пробуем извлечь промпт из сообщения
            extracted_text = ""
            if message.text:
                extracted_text = message.text
            
            # Пробуем извлечь модель
            model = self.extract_model_from_text(extracted_text)
            if not model:
                model = "Unknown"
                
            # Извлекаем ID сообщения как ID промпта
            prompt_id = str(message.id)
            
            # Генерируем имя файла
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            model_name = model.split()[0].replace('🌙', '').replace('➕', '').replace('📦', '')\
                         .replace('🎬', '').replace('🎯', '').replace('👁', '')\
                         .replace('🌫', '').replace('🦋', '').strip()
            
            # Формируем сокращенный промпт для имени файла
            prompt_short = "unknown"
            if extracted_text:
                # Выбираем текст после "Ваш запрос:" если есть
                prompt_match = re.search(r'Ваш запрос:?\s*`?(.*?)`?$', extracted_text, re.MULTILINE)
                if prompt_match:
                    prompt_text = prompt_match.group(1).strip()
                    prompt_short = self.get_first_5_words(prompt_text)
                    prompt_short = self.sanitize_filename(prompt_short)
                else:
                    # Если не нашли, берем первые 5 слов из всего текста
                    prompt_short = self.get_first_5_words(extracted_text)
                    prompt_short = self.sanitize_filename(prompt_short)
            
            # Формируем имя файла
            file_name = f"{timestamp}_{prompt_id}_{model_name}_{prompt_short}.mp4"
            file_path = os.path.join(self.download_path, file_name)
            
            print(f"ℹ️ Информация о видео: {message.media.document.mime_type}, размер: {message.media.document.size} байт")
            print(f"⏳ Начинаем загрузку произвольного видео в файл: {file_path}")
            
            # Получаем клиент для загрузки
            from telethon import TelegramClient
            client = None
            if hasattr(self, 'client') and isinstance(self.client, TelegramClient):
                client = self.client
            elif self.message_monitor and hasattr(self.message_monitor, 'client'):
                client = self.message_monitor.client
                
            # Скачиваем файл
            await message.download_media(file_path)
            
            print(f"✅ Видео успешно загружено: {file_path}")
            
            # Логируем успешную загрузку
            if self.logger:
                self.logger.log_app_event("VIDEO_DOWNLOADED", 
                                        f"Загружено произвольное видео: {file_path}", 
                                        extra_info={"prompt_id": prompt_id, "model": model})
            
            # Сохраняем информацию о последнем скачивании
            self.last_download_success = True
            self.last_saved_filepath = file_path
            return True
            
        except Exception as e:
            error_message = f"❌ Ошибка при скачивании произвольного видео: {str(e)}"
            print(error_message)
            
            if self.logger:
                self.logger.log_app_event("VIDEO_ERROR", 
                                        f"Ошибка загрузки произвольного видео: {str(e)}", 
                                        "ERROR")
                self.logger.log_exception(e, context="При скачивании произвольного видео")
            
            self.last_download_success = False
            return False

    async def start_monitoring(self):
        # Проверяем, активен ли монитор сообщений
        if hasattr(self, 'monitoring_active') and self.monitoring_active:
            return
        
        self.monitoring_active = True
        
        @self.client.on(events.NewMessage(chats=self.bot))
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

        @self.client.on(events.MessageEdited(chats=self.bot))
        async def edited_handler(event):
            # Обработка отредактированных сообщений
            try:
                message_text = event.message.text or ""
                has_video = (hasattr(event.message, 'media') and 
                             event.message.media and 
                             hasattr(event.message.media, 'document') and 
                             event.message.media.document.mime_type.startswith('video/'))
                
                # Проверяем, нужно ли обрабатывать это сообщение
                from message_filter import MessageFilter
                message_filter = MessageFilter()
                if not message_filter.should_process_edited_message(message_text, has_video):
                    return
                
                # Если есть видео в отредактированном сообщении
                if has_video:
                    # Определяем модель из текста сообщения
                    model = self.extract_model_from_text(message_text)
                    
                    # Если есть текущий промпт, скачиваем видео
                    current_prompt = self.get_current_prompt()
                    if current_prompt:
                        await self.download_video(event.message, current_prompt, model)
                        if self.logger:
                            self.logger.log_app_event("VIDEO_DOWNLOADED_EDITED", 
                                                   f"Скачано видео из отредактированного сообщения для промпта: {current_prompt[:30]}...")
            except Exception as e:
                if self.logger:
                    self.logger.log_exception(e, context="При обработке отредактированного сообщения в VideoDownloader")

    def set_current_prompt(self, prompt, model):
        self.current_prompt = prompt
        self.current_model = model 