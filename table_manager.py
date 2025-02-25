import csv
import os
import hashlib
from datetime import datetime

class TableManager:
    def __init__(self, config):
        self.base_path = config.get('downloads_path', 'downloaded_videos')
        self.table_file = os.path.join(self.base_path, config.get('table_file', 'prompts_table.csv'))
        self.headers = ['id', 'prompt', 'status', 'model', 'video_path', 'timestamp', 'slot', 'attempt_count', 'last_status_message']
        
        # Статусы промптов
        self.STATUS_PENDING = 'pending'          # Ожидает обработки
        self.STATUS_QUEUED = 'queued'           # В очереди на обработку
        self.STATUS_PROMPT_SENT = 'prompt_sent'  # Промпт отправлен
        self.STATUS_GENERATION_STARTED = 'generation_started'  # Генерация началась
        self.STATUS_WAITING_VIDEO = 'waiting_video'  # Ожидание видео
        self.STATUS_IN_PROGRESS = 'in_progress'  # В процессе обработки
        self.STATUS_COMPLETED = 'completed'      # Успешно завершен
        self.STATUS_ERROR = 'error'             # Ошибка при обработке
        self.STATUS_LIMIT_REACHED = 'limit_reached'  # Достигнут лимит запросов
        self.STATUS_SKIPPED = 'skipped'         # Пропущен пользователем
        self.STATUS_TIMEOUT = 'timeout'         # Превышено время ожидания
        
        self.clear_table()

    def clear_table(self):
        """Создает новую таблицу или очищает существующую"""
        os.makedirs(os.path.dirname(self.table_file), exist_ok=True)
        with open(self.table_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=self.headers)
            writer.writeheader()

    def _ensure_table_exists(self):
        """Проверяет существование таблицы и создает если нужно"""
        if not os.path.exists(self.table_file):
            self.clear_table()

    def generate_prompt_id(self, prompt):
        hash_object = hashlib.md5(prompt.encode())
        return hash_object.hexdigest()[:8]

    def load_prompts(self, prompt_file):
        with open(prompt_file, 'r', encoding='utf-8') as f:
            prompts = [p.strip() for p in f.read().split('\n\n') if p.strip()]

        new_prompts = []
        for prompt in prompts:
            new_prompts.append({
                'id': self.generate_prompt_id(prompt),
                'prompt': prompt,
                'status': 'pending',
                'model': '',
                'video_path': '',
                'timestamp': ''
            })

        self._write_table(new_prompts)
        return new_prompts

    def _read_table(self):
        """Читает всю таблицу"""
        self._ensure_table_exists()
        with open(self.table_file, 'r', encoding='utf-8') as f:
            return list(csv.DictReader(f))

    def _write_table(self, rows):
        with open(self.table_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=self.headers)
            writer.writeheader()
            writer.writerows(rows)

    def update_status(self, prompt_id, status, model='', video_path='', slot='', status_message=''):
        """Обновляет статус и другие поля промпта"""
        rows = self._read_table()
        for row in rows:
            if row['id'] == prompt_id:
                row['status'] = status
                if model:
                    row['model'] = model
                if video_path:
                    row['video_path'] = video_path
                if slot:
                    row['slot'] = str(slot)
                row['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Обновляем счетчик попыток для некоторых статусов
                if status in [self.STATUS_PROMPT_SENT]:
                    try:
                        attempt_count = int(row.get('attempt_count', '0')) + 1
                    except ValueError:
                        # Если attempt_count не является числом или пустая строка
                        attempt_count = 1
                    row['attempt_count'] = str(attempt_count)
                
                # Записываем последнее статусное сообщение
                if status_message:
                    row['last_status_message'] = status_message
                
        self._write_table(rows)

    def mark_queued(self, prompt_id, slot_number):
        """Отмечает промпт как добавленный в очередь"""
        self.update_status(prompt_id, self.STATUS_QUEUED, slot=slot_number)

    def mark_timeout(self, prompt_id, model=''):
        """Отмечает таймаут при обработке промпта"""
        self.update_status(prompt_id, self.STATUS_TIMEOUT, model=model)

    def get_slot_prompts(self, slot_number):
        """Получает список промптов для конкретного слота"""
        return [row for row in self._read_table() if row.get('slot') == str(slot_number)]

    def get_active_prompts(self):
        """Получает список активных промптов (в очереди или в обработке)"""
        return [row for row in self._read_table() 
               if row['status'] in [self.STATUS_QUEUED, self.STATUS_IN_PROGRESS]]

    def mark_in_progress(self, prompt_id, model=''):
        """Отмечает промпт как находящийся в обработке"""
        self.update_status(prompt_id, self.STATUS_IN_PROGRESS, model=model)

    def mark_error(self, prompt_id, model=''):
        """Отмечает ошибку при обработке промпта"""
        self.update_status(prompt_id, self.STATUS_ERROR, model=model)

    def mark_completed(self, prompt_id, model='', video_path=''):
        """Отмечает успешное завершение обработки промпта"""
        self.update_status(prompt_id, self.STATUS_COMPLETED, model=model, video_path=video_path)

    def mark_skipped(self, prompt_id):
        """Отмечает пропущенный промпт"""
        self.update_status(prompt_id, self.STATUS_SKIPPED)

    def get_status(self, prompt_id):
        rows = self._read_table()
        for row in rows:
            if row['id'] == prompt_id:
                return row
        return None

    def get_in_progress_prompts(self):
        """Получает список промптов в обработке"""
        return [row for row in self._read_table() if row['status'] == self.STATUS_IN_PROGRESS]

    def get_pending_prompts(self):
        """Получает список необработанных промптов"""
        return [row for row in self._read_table() if row['status'] == self.STATUS_PENDING]

    def mark_pending(self, prompt_id):
        """Возвращает промпт в состояние ожидания"""
        self.update_status(prompt_id, self.STATUS_PENDING, slot='')

    def mark_prompt_sent(self, prompt_id, model=''):
        """Отмечает, что промпт был отправлен боту"""
        self.update_status(prompt_id, self.STATUS_PROMPT_SENT, model=model)
    
    def mark_generation_started(self, prompt_id, model='', status_message=''):
        """Отмечает, что бот начал генерацию видео"""
        self.update_status(prompt_id, self.STATUS_GENERATION_STARTED, model=model, status_message=status_message)
    
    def mark_waiting_video(self, prompt_id, model=''):
        """Отмечает, что система ожидает получения видео"""
        self.update_status(prompt_id, self.STATUS_WAITING_VIDEO, model=model)
    
    def mark_limit_reached(self, prompt_id, status_message=''):
        """Отмечает, что достигнут лимит запросов"""
        self.update_status(prompt_id, self.STATUS_LIMIT_REACHED, status_message=status_message) 