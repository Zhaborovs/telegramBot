import os
from datetime import datetime

class MessageLogger:
    def __init__(self):
        self.log_dir = 'logs'
        self.log_file = 'messages.log'
        self.old_log_file = 'messages_old.log'
        self.setup_logging()

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

    def log_message(self, message_text, has_video=False, extra_info=None):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Формируем строку лога
        log_entry = f"[{timestamp}] "
        if has_video:
            log_entry += "[ВИДЕО] "
        
        log_entry += message_text

        if extra_info:
            log_entry += f" | Доп. инфо: {extra_info}"

        # Записываем в файл
        with open(self.current_log_path, 'a', encoding='utf-8') as f:
            f.write(log_entry + '\n') 