import os
from datetime import datetime
import logging
import traceback
import sys

class MessageLogger:
    def __init__(self):
        self.log_dir = 'logs'
        self.log_file = 'messages.log'
        self.old_log_file = 'messages_old.log'
        self.debug_log_file = 'debug.log'
        self.error_log_file = 'error.log'
        self.setup_logging()
        
        # Настраиваем логгеры
        self.message_logger = self._setup_logger('message_logger', os.path.join(self.log_dir, self.log_file))
        self.debug_logger = self._setup_logger('debug_logger', os.path.join(self.log_dir, self.debug_log_file))
        self.error_logger = self._setup_logger('error_logger', os.path.join(self.log_dir, self.error_log_file))

    def setup_logging(self):
        # Создаем директорию для логов, если её нет
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)

        # Полные пути к файлам
        self.current_log_path = os.path.join(self.log_dir, self.log_file)
        self.old_log_path = os.path.join(self.log_dir, self.old_log_file)

        # Если текущий лог существует, перемещаем его в old
        if os.path.exists(self.current_log_path):
            # Если old лог существует, удаляем его
            if os.path.exists(self.old_log_path):
                os.remove(self.old_log_path)
            # Перемещаем текущий лог в old
            os.rename(self.current_log_path, self.old_log_path)
    
    def _setup_logger(self, name, log_file, level=logging.INFO):
        """Настраивает и возвращает логгер с указанным именем и файлом"""
        handler = logging.FileHandler(log_file, encoding='utf-8')
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        
        logger = logging.getLogger(name)
        logger.setLevel(level)
        
        # Удаляем существующие обработчики, если они есть
        if logger.handlers:
            for handler in logger.handlers:
                logger.removeHandler(handler)
                
        logger.addHandler(handler)
        
        # Отключаем распространение логов на родительские логгеры
        logger.propagate = False
        
        return logger
        
    def log_message(self, message_text, has_video=False, extra_info=None):
        """Логирует сообщение в файл"""
        try:
            # Записываем в лог-файл
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            log_entry = f"[{timestamp}] {message_text}"
            
            # Добавляем информацию о видео, если есть
            if has_video:
                log_entry += " | Содержит видео"
                
            # Добавляем дополнительную информацию, если есть
            if extra_info:
                log_entry += f" | {extra_info}"
                
            # Записываем в лог
            try:
                self.message_logger.info(message_text + (f" | {extra_info}" if extra_info else ""))
            except UnicodeEncodeError as e:
                # Если возникла ошибка кодировки, заменяем проблемные символы
                safe_message = message_text.encode('ascii', 'replace').decode('ascii')
                self.message_logger.info(f"[UNICODE ERROR] {safe_message}" + (f" | {extra_info}" if extra_info else ""))
                self.error_logger.error(f"Ошибка кодировки при логировании: {str(e)}")
        except Exception as e:
            # Логируем ошибку в отдельный файл
            error_msg = f"Ошибка при логировании сообщения: {str(e)}"
            self.error_logger.error(error_msg)
            self.error_logger.error(traceback.format_exc())
    
    def log_debug(self, message, extra_info=None):
        """Логирует отладочную информацию"""
        log_message = message
        if extra_info:
            log_message += f" | {extra_info}"
        self.debug_logger.debug(log_message)
        print(f"[DEBUG] {log_message}")
    
    def log_info(self, message, extra_info=None):
        """Логирует информационное сообщение"""
        log_message = message
        if extra_info:
            log_message += f" | {extra_info}"
        self.debug_logger.info(log_message)
        print(f"[INFO] {log_message}")
    
    def log_error(self, message, error=None, extra_info=None):
        """Логирует ошибку с трассировкой стека"""
        log_message = message
        
        if error:
            log_message += f" | Ошибка: {str(error)}"
            error_traceback = traceback.format_exc()
            log_message += f"\n{error_traceback}"
        
        if extra_info:
            log_message += f" | {extra_info}"
            
        self.error_logger.error(log_message)
        print(f"[ERROR] {message}")
    
    def log_slot_status(self, slot, status, message=None):
        """Логирует изменение статуса слота"""
        log_message = f"Слот {slot}: {status}"
        if message:
            log_message += f" | {message}"
        self.debug_logger.info(log_message)
        print(f"[SLOT] {log_message}") 