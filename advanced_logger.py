import os
import logging
from datetime import datetime
import json

class AdvancedLogger:
    """
    Расширенный логгер для Telegram бота, который ведет отдельные логи для:
    - Исходящих сообщений (от бота)
    - Входящих сообщений (от пользователя)
    - Действий программы
    """
    
    def __init__(self, config=None):
        """
        Инициализирует логгер с настройками
        
        Args:
            config: Словарь с настройками или объект конфигурации
        """
        self.log_dir = 'logs'
        self.log_level = logging.INFO
        
        # Загружаем настройки из конфига, если он предоставлен
        if config:
            if isinstance(config, dict):
                self.log_dir = config.get('log_dir', 'logs')
                self.log_level_str = config.get('log_level', 'INFO')
            else:
                self.log_dir = config.log_dir if hasattr(config, 'log_dir') else 'logs'
                self.log_level_str = getattr(config, 'log_level', 'INFO')
            
            # Преобразуем строковое представление уровня логирования в константу
            level_map = {
                'DEBUG': logging.DEBUG,
                'INFO': logging.INFO,
                'WARNING': logging.WARNING,
                'ERROR': logging.ERROR,
                'CRITICAL': logging.CRITICAL
            }
            self.log_level = level_map.get(self.log_level_str.upper(), logging.INFO)
        
        # Устанавливаем логгеры
        self.setup_logging()
        
    def setup_logging(self):
        """Настраивает все необходимые логгеры"""
        # Создаем директорию для логов, если её нет
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
            
        # Настраиваем логи для исходящих сообщений
        self.outgoing_logger = self._setup_channel_logger('outgoing')
        
        # Настраиваем логи для входящих сообщений
        self.incoming_logger = self._setup_channel_logger('incoming')
        
        # Настраиваем логи для действий программы
        self.app_logger = self._setup_channel_logger('app')
        
        # Настраиваем логи для видео и медиа
        self.media_logger = self._setup_channel_logger('media')
        
        # Общий логгер для всех событий
        self.all_logger = self._setup_channel_logger('all')
        
        # Логгер ошибок
        self.error_logger = self._setup_channel_logger('error', level=logging.ERROR)
    
    def _setup_channel_logger(self, channel_name, level=None):
        """
        Создает и настраивает логгер для указанного канала
        
        Args:
            channel_name: Имя канала логирования
            level: Уровень логирования для данного канала
        
        Returns:
            Logger: Настроенный объект логгера
        """
        if level is None:
            level = self.log_level
            
        # Создаем логгер
        logger = logging.getLogger(f'telegram_bot.{channel_name}')
        logger.setLevel(level)
        logger.handlers = []  # Очищаем существующие обработчики
        
        # Создаем обработчик для записи в файл
        file_handler = logging.FileHandler(
            os.path.join(self.log_dir, f'{channel_name}.log'), 
            encoding='utf-8'
        )
        file_handler.setLevel(level)
        
        # Настраиваем формат вывода
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        
        # Добавляем обработчик к логгеру
        logger.addHandler(file_handler)
        
        # Отключаем propagation чтобы избежать дублирования
        logger.propagate = False
        
        return logger
    
    def log_outgoing(self, message, recipient=None, message_type="TEXT", extra_info=None):
        """
        Логирует исходящие сообщения (от нашего бота)
        
        Args:
            message: Текст сообщения
            recipient: Получатель сообщения
            message_type: Тип сообщения (TEXT, COMMAND, PROMPT)
            extra_info: Дополнительная информация
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] ОТПРАВЛЕНО -> {recipient or 'Unknown'} [{message_type}]: {message}"
        
        if extra_info:
            # Если extra_info это словарь, форматируем его как JSON
            if isinstance(extra_info, dict):
                extra_info = json.dumps(extra_info, ensure_ascii=False)
            log_message += f" | {extra_info}"
        
        self.outgoing_logger.info(log_message)
        self.all_logger.info(log_message)
        
        # Логируем команды отдельно, если это команда
        if message_type == "COMMAND" or message.startswith('/'):
            self.app_logger.info(f"[COMMAND] {message} -> {recipient or 'Unknown'}")
        
        # Логируем промпты отдельно, если это промпт
        if message_type == "PROMPT":
            self.app_logger.info(f"[PROMPT] Промпт отправлен -> {recipient or 'Unknown'} | {message[:50]}...")
        
    def log_incoming(self, message, sender=None, has_media=False, media_type=None, extra_info=None):
        """
        Логирует входящие сообщения (к нашему боту)
        
        Args:
            message: Текст сообщения
            sender: Отправитель сообщения
            has_media: Флаг наличия медиа
            media_type: Тип медиа (VIDEO, IMAGE, ANIMATION)
            extra_info: Дополнительная информация
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        media_prefix = ""
        if has_media:
            media_prefix = f"[{media_type or 'MEDIA'}] "
        
        log_message = f"[{timestamp}] ПОЛУЧЕНО <- {sender or 'Unknown'}: {media_prefix}{message}"
        
        if extra_info:
            if isinstance(extra_info, dict):
                extra_info = json.dumps(extra_info, ensure_ascii=False)
            log_message += f" | {extra_info}"
        
        self.incoming_logger.info(log_message)
        self.all_logger.info(log_message)
        
        # Если сообщение содержит медиа, логируем его также в медиа логгер
        if has_media:
            self.media_logger.info(f"[{timestamp}] {media_type or 'MEDIA'} от {sender or 'Unknown'}: {message}")
    
    def log_app_event(self, event_type, description, level="INFO", extra_info=None):
        """
        Логирует события в программе
        
        Args:
            event_type: Тип события
            description: Описание события
            level: Уровень логирования (INFO, DEBUG, WARNING, ERROR, CRITICAL)
            extra_info: Дополнительная информация
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] [{event_type}] {description}"
        
        if extra_info:
            if isinstance(extra_info, dict):
                extra_info = json.dumps(extra_info, ensure_ascii=False)
            log_message += f" | {extra_info}"
            
        all_message = log_message  # Копия для all_logger
        
        # Выбираем соответствующий метод логирования в зависимости от уровня
        if level.upper() == "DEBUG":
            self.app_logger.debug(log_message)
            self.all_logger.debug(all_message)
        elif level.upper() == "WARNING":
            self.app_logger.warning(log_message)
            self.all_logger.warning(all_message)
        elif level.upper() == "ERROR":
            self.app_logger.error(log_message)
            self.all_logger.error(all_message)
            self.error_logger.error(log_message)
        elif level.upper() == "CRITICAL":
            self.app_logger.critical(log_message)
            self.all_logger.critical(all_message)
            self.error_logger.critical(log_message)
        else:
            self.app_logger.info(log_message)
            self.all_logger.info(all_message)
    
    def log_video_downloaded(self, prompt_id, filename, model, success=True, error=None):
        """
        Логирует информацию о загруженном видео
        
        Args:
            prompt_id: ID промпта
            filename: Имя файла видео
            model: Модель, которая создала видео
            success: Флаг успешной загрузки
            error: Сообщение об ошибке (если есть)
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if success:
            log_message = f"[{timestamp}] [VIDEO] Загружено видео | Промпт: {prompt_id} | Модель: {model} | Файл: {filename}"
            self.media_logger.info(log_message)
            self.all_logger.info(log_message)
        else:
            log_message = f"[{timestamp}] [VIDEO_ERROR] Ошибка загрузки видео | Промпт: {prompt_id} | Модель: {model} | {error}"
            self.media_logger.error(log_message)
            self.error_logger.error(log_message)
            self.all_logger.error(log_message)
    
    def log_model_limit(self, model, limit_value, prompt_id=None):
        """
        Логирует информацию о достижении лимита модели
        
        Args:
            model: Название модели
            limit_value: Значение лимита
            prompt_id: ID промпта (если есть)
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prompt_info = f" | Промпт: {prompt_id}" if prompt_id else ""
        
        log_message = f"[{timestamp}] [MODEL_LIMIT] Достигнут лимит модели: {model} (значение: {limit_value}){prompt_info}"
        self.app_logger.warning(log_message)
        self.all_logger.warning(log_message)
    
    def log_startup(self):
        """Логирует запуск приложения"""
        self.log_app_event("STARTUP", "Приложение запущено", "INFO", 
                          {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    
    def log_shutdown(self):
        """Логирует завершение работы приложения"""
        self.log_app_event("SHUTDOWN", "Приложение завершило работу", "INFO", 
                          {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    
    def log_exception(self, exception, context=None):
        """
        Логирует исключение
        
        Args:
            exception: Объект исключения
            context: Контекст, в котором произошло исключение
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        log_message = f"[{timestamp}] [EXCEPTION] {type(exception).__name__}: {str(exception)}"
        if context:
            if isinstance(context, dict):
                context = json.dumps(context, ensure_ascii=False)
            log_message += f" | Контекст: {context}"
        
        self.error_logger.error(log_message)
        self.app_logger.error(log_message)
        self.all_logger.error(log_message)

# Пример использования:
# logger = AdvancedLogger()
# logger.log_outgoing("/video", "TelegramBot", "COMMAND")
# logger.log_incoming("Ответ от бота", "User123", has_media=True, media_type="VIDEO")
# logger.log_app_event("PROMPT_PROCESS", "Обработан промпт", extra_info={"prompt_id": "abc123"}) 