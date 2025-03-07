import os
from datetime import datetime

class TaskManager:
    def __init__(self, client, downloader, model_counter, logger=None):
        """
        Инициализирует менеджер задач.
        
        Args:
            client: Клиент Telegram
            downloader: Загрузчик видео
            model_counter: Счетчик использования моделей
            logger: Логгер для записи событий
        """
        self.client = client
        self.downloader = downloader
        self.model_counter = model_counter
        self.logger = logger
        self.download_path = "downloaded_videos"  # Путь для сохранения видео
        
        # Создаем директорию, если её нет
        if not os.path.exists(self.download_path):
            os.makedirs(self.download_path)
            if logger:
                logger.info(f"[INIT] Создана директория для сохранения видео: {self.download_path}")
        
        # Устанавливаем client для загрузчика при инициализации
        if downloader and hasattr(downloader, 'set_client'):
            self.downloader.set_client(client)
            if logger:
                logger.info(f"[INIT] Client установлен для загрузчика видео при инициализации")

    def get_video_path(self, prompt_id, model_name):
        """
        Формирует путь для сохранения видео.
        
        Args:
            prompt_id: Идентификатор промпта
            model_name: Название модели
            
        Returns:
            str: Путь к файлу видео
        """
        # Удаляем emoji из названия модели
        model_clean = ''.join(c for c in model_name if c.isalnum() or c.isspace()).strip()
        # Формируем имя файла с датой, ID промпта и моделью
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{prompt_id}_{model_clean}.mp4"
        # Полный путь к файлу
        video_path = os.path.join(self.download_path, filename)
        
        return video_path

    def process_video_received(self, message, has_video=False):
        """Обрабатывает полученное видео."""
        try:
            # Извлекаем необходимые данные из сообщения
            prompt_id = message.message_id
            model_name = self.get_model_from_message(message)  # Предполагаем, что такой метод существует
            slot = self.get_available_slot()  # Предполагаем, что такой метод существует
            
            # Проверяем наличие видео в сообщении
            if has_video:
                video_path = self.get_video_path(prompt_id, model_name)  # Формируем путь для сохранения видео
                self.logger.info(f"[VIDEO_PROCESSING] Обработка видео для промпта {prompt_id} в слоте {slot}")
                
                # Скачиваем видео
                try:
                    # Убедимся, что client установлен для загрузчика
                    if hasattr(self, 'client') and self.client:
                        self.downloader.set_client(self.client)
                        self.logger.info(f"[CLIENT_SET] Client установлен для загрузчика видео")
                    
                    self.downloader.download_video(message, video_path)
                    self.logger.info(f"[VIDEO_DOWNLOADED] Видео сохранено в {video_path}")
                    
                    # Уменьшаем счетчик только ОДИН раз здесь, после успешного скачивания
                    self.model_counter.decrease(model_name)
                    self.logger.info(f"[MODEL_COUNTER] Уменьшен счетчик модели {model_name} | value: {self.model_counter.get_count(model_name)}")
                    
                    # Отмечаем промпт как завершенный сразу после успешного скачивания
                    self.update_prompt_status(prompt_id, "completed")
                    self.logger.info(f"[PROMPT_COMPLETED] Промпт {prompt_id} успешно обработан в слоте {slot}")
                    
                except Exception as e:
                    self.logger.error(f"[VIDEO_ERROR] Ошибка загрузки видео | Промпт: {prompt_id} | Модель: {model_name} | {str(e)}")
                    self.logger.error(f"[EXCEPTION] {type(e).__name__}: {str(e)} | Контекст: При скачивании видео для промпта {prompt_id}")
                    # НЕ уменьшаем счетчик при ошибке загрузки
                    self.update_prompt_status(prompt_id, "error")
                    return
            else:
                # Если видео не требуется, просто отмечаем промпт как завершенный
                self.update_prompt_status(prompt_id, "completed")
                self.logger.info(f"[PROMPT_COMPLETED] Промпт {prompt_id} успешно обработан в слоте {slot} (без видео)")
            
        except Exception as e:
            self.logger.error(f"[PROCESS_ERROR] Ошибка обработки для промпта {prompt_id if 'prompt_id' in locals() else 'неизвестный'} | {str(e)}")
            self.logger.error(f"[EXCEPTION] {type(e).__name__}: {str(e)} | Контекст: При обработке видео")
            
            # Обновляем статус промпта, если ID промпта определен
            if 'prompt_id' in locals():
                self.update_prompt_status(prompt_id, "error")
        
        finally:
            # Освобождаем слот и запускаем следующий промпт независимо от результата
            if 'slot' in locals():
                self.release_slot(slot)  # Предполагаем, что такой метод существует
                self.process_queue()  # Запускаем обработку следующего промпта в очереди 