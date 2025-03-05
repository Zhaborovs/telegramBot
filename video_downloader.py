import os
import asyncio
from telethon import events
import re
from datetime import datetime

class VideoDownloader:
    def __init__(self, table_manager, config, logger=None):
        self.table_manager = table_manager
        self.config = config
        self.logger = logger
        self.base_path = config.get('downloads_path', 'downloaded_videos')
        self.retry_attempts = int(config.get('retry_attempts', '3'))
        self.download_path = "downloaded_videos"
        self.last_download_success = False
        self.last_saved_filepath = None
        self.current_download = None
        
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
        try:
            self.current_download = prompt_id
            filename = self.get_video_filename(prompt_id, model)
            filepath = os.path.join(self.base_path, filename)
            
            print(f"Начинаю скачивание видео: {filename}")
            if self.logger:
                self.logger.log_app_event("DOWNLOAD_START", f"Начинаем скачивание видео для промпта {prompt_id}",
                                      extra_info={"filename": filename, "model": model})
                
            await message.download_media(filepath)
            await asyncio.sleep(2)
            
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                print(f"Видео успешно сохранено: {filepath}")
                self.table_manager.mark_completed(prompt_id, model, filepath)
                
                if self.logger:
                    self.logger.log_video_downloaded(prompt_id, filename, model, success=True)
                    
                return True
            else:
                error_message = "Ошибка: файл не был создан или пустой"
                print(error_message)
                self.table_manager.mark_error(prompt_id, model)
                
                if self.logger:
                    self.logger.log_video_downloaded(prompt_id, filename, model, success=False, error=error_message)
                    
                return False
                
        except Exception as e:
            error_message = f"Ошибка при скачивании видео: {e}"
            print(error_message)
            self.table_manager.mark_error(prompt_id, model)
            
            if self.logger:
                self.logger.log_video_downloaded(prompt_id, filename, model, success=False, error=str(e))
                self.logger.log_exception(e, context=f"При скачивании видео для промпта {prompt_id}")
                
            return False
        finally:
            self.current_download = None
            
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
            
            # Извлекаем промпт из сообщения, если есть формат "📍 Ваш запрос:" или "**📍 Ваш запрос:**"
            extracted_prompt = None
            prompt_patterns = [
                r'(?:\*\*)?📍\s+Ваш\s+запрос:(?:\*\*)?\s+`?(.*?)`?(?=\n|$)',
                r'Ваш\s+запрос:\s+`?(.*?)`?(?=\n|$)'
            ]
            
            for pattern in prompt_patterns:
                prompt_match = re.search(pattern, message_text, re.IGNORECASE | re.DOTALL)
                if prompt_match:
                    extracted_prompt = prompt_match.group(1).strip()
                    print(f"Извлечен промпт из сообщения: '{extracted_prompt[:50]}...'")
                    break
            
            # Если нашли промпт в сообщении, ищем совпадение в таблице
            if extracted_prompt:
                # Сначала ищем точное совпадение
                for prompt in all_prompts:
                    table_prompt_text = prompt.get('prompt', '')
                    # Проверяем на точное совпадение или аналогичный текст (без учета регистра)
                    if table_prompt_text and (
                        table_prompt_text.lower() == extracted_prompt.lower() or
                        table_prompt_text.lower() in extracted_prompt.lower() or
                        extracted_prompt.lower() in table_prompt_text.lower()
                    ):
                        found_prompt = prompt
                        prompt_text = table_prompt_text
                        print(f"Найдено точное совпадение промпта: '{prompt_text[:50]}...' (ID: {found_prompt['id']})")
                        break
                
                # Если точное совпадение не найдено, используем нечеткое совпадение
                if not found_prompt:
                    best_match = None
                    best_ratio = 0
                    for prompt in all_prompts:
                        table_prompt_text = prompt.get('prompt', '')
                        if not table_prompt_text:
                            continue
                            
                        # Простая метрика совпадения: количество общих слов
                        table_words = set(table_prompt_text.lower().split())
                        extracted_words = set(extracted_prompt.lower().split())
                        
                        if not table_words or not extracted_words:
                            continue
                            
                        common_words = table_words & extracted_words
                        ratio = len(common_words) / max(len(table_words), len(extracted_words))
                        
                        if ratio > best_ratio and ratio > 0.5:  # Считаем совпадением, если более 50% слов совпадают
                            best_ratio = ratio
                            best_match = prompt
                    
                    if best_match:
                        found_prompt = best_match
                        prompt_text = found_prompt.get('prompt', '')
                        print(f"Найдено нечеткое совпадение промпта: '{prompt_text[:50]}...' (ID: {found_prompt['id']}), совпадение: {best_ratio:.2f}")
            
            # Если промпт не найден ни в тексте, ни через сопоставление, пытаемся найти по модели
            if not found_prompt and model_name and active_prompts:
                matching_prompts = [p for p in active_prompts if p.get('model') == model_name]
                if matching_prompts:
                    found_prompt = matching_prompts[0]  # Берем первый совпадающий по модели
                    prompt_text = found_prompt.get('prompt', '')
                    print(f"Найден активный промпт для модели {model_name}: '{prompt_text[:50]}...' (ID: {found_prompt['id']})")
                else:
                    # Если нет совпадений по модели, берем первый активный
                    found_prompt = active_prompts[0]
                    prompt_text = found_prompt.get('prompt', '')
                    print(f"Взят первый активный промпт: '{prompt_text[:50]}...' (ID: {found_prompt['id']})")
            
            # Если промпт найден, используем его ID
            if found_prompt:
                prompt_id = found_prompt['id']
                
                # Если модель не задана, используем модель из промпта
                if not model_name:
                    model = found_prompt.get('model', 'unknown')
                
                # Извлекаем модель из сообщения (если не задана)
                if model == 'unknown' and message_text:
                    extracted_model = self.extract_model_from_text(message_text)
                    if extracted_model:
                        model = extracted_model
                        print(f"Извлечена модель из сообщения: {model}")
                
                # Генерируем имя файла на основе промпта
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                model_short = model.split()[0].replace('🌙', '').replace('➕', '').replace('📦', '')\
                            .replace('🎬', '').replace('🎯', '').replace('👁', '')\
                            .replace('🌫', '').replace('🦋', '').strip()
                
                # Создаем имя файла на основе найденного промпта
                # Если у нас есть извлеченный промпт из сообщения, используем его для имени файла
                if extracted_prompt:
                    prompt_for_filename = extracted_prompt
                else:
                    prompt_for_filename = prompt_text
                
                # Очищаем от спецсимволов и получаем первые 5 слов
                prompt_words = self.get_first_5_words(prompt_for_filename)
                prompt_words = self.sanitize_filename(prompt_words)
                
                filename = f"{timestamp}_{prompt_id}_{model_short}_{prompt_words}.mp4"
            else:
                # Если промпт не найден, сохраняем с временным именем, но пытаемся извлечь из сообщения
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                
                # Если модель не определена, пытаемся извлечь из сообщения
                if model == 'unknown' and message_text:
                    extracted_model = self.extract_model_from_text(message_text)
                    if extracted_model:
                        model = extracted_model
                        print(f"Извлечена модель из сообщения для неизвестного промпта: {model}")
                
                # Получаем короткое имя модели
                model_short = model.split()[0].replace('🌙', '').replace('➕', '').replace('📦', '')\
                            .replace('🎬', '').replace('🎯', '').replace('👁', '')\
                            .replace('🌫', '').replace('🦋', '').strip()
                
                # Если удалось извлечь промпт из сообщения, используем его в имени файла
                if extracted_prompt:
                    prompt_words = self.get_first_5_words(extracted_prompt)
                    prompt_words = self.sanitize_filename(prompt_words)
                    filename = f"unknown_{timestamp}_{model_short}_{prompt_words}.mp4"
                else:
                    filename = f"unknown_{timestamp}_{model_short}.mp4"
                
                print(f"Промпт не найден в таблице, сохраняем видео как: {filename}")
            
            # Создаем путь к файлу и скачиваем видео
            filepath = os.path.join(self.base_path, filename)
            
            print(f"Скачивание видео для промпта {prompt_id if prompt_id else 'неизвестно'} с моделью {model}: {filename}")
            if self.logger:
                self.logger.log_app_event("DOWNLOAD_START", 
                                      f"Скачивание видео для промпта {prompt_id if prompt_id else 'неизвестно'}", 
                                      extra_info={"model": model, "filename": filename})
                
            await message.download_media(filepath)
            
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                print(f"Видео успешно сохранено: {filepath}")
                self.last_saved_filepath = filepath
                self.last_download_success = True
                
                if self.logger:
                    self.logger.log_video_downloaded(
                        prompt_id=prompt_id or "unknown",
                        filename=filename,
                        model=model,
                        success=True
                    )
                
                # Отмечаем промпт как завершенный, если он был найден
                if prompt_id:
                    self.table_manager.mark_completed(prompt_id, model, filepath)
                return True
            else:
                error_message = "Ошибка: файл не был создан или пустой"
                print(error_message)
                self.last_download_success = False
                
                if self.logger:
                    self.logger.log_video_downloaded(
                        prompt_id=prompt_id or "unknown",
                        filename=filename,
                        model=model,
                        success=False,
                        error=error_message
                    )
                    
                return False
                
        except Exception as e:
            error_message = f"Ошибка при скачивании видео: {e}"
            print(error_message)
            self.last_download_success = False
            
            if self.logger:
                self.logger.log_exception(e, context="При скачивании видео без привязки к промпту")
                
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