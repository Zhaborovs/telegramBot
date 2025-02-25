import csv
import os
import hashlib
from datetime import datetime

class PromptTable:
    def __init__(self):
        self.base_path = "downloaded_videos"
        if not os.path.exists(self.base_path):
            os.makedirs(self.base_path)
            
        self.table_file = os.path.join(self.base_path, "prompts_table.csv")
        self.headers = ['id', 'prompt', 'status', 'model', 'video_path', 'timestamp']
        self.clear_table()

    def clear_table(self):
        """Очищает таблицу, оставляя только заголовки"""
        with open(self.table_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=self.headers)
            writer.writeheader()

    def generate_prompt_id(self, prompt):
        """Генерирует уникальный ID для промпта"""
        hash_object = hashlib.md5(prompt.encode())
        return hash_object.hexdigest()[:8]

    def load_prompts_from_file(self, prompt_file):
        """Загружает промпты из файла в таблицу"""
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
        with open(self.table_file, 'r', encoding='utf-8') as f:
            return list(csv.DictReader(f))

    def _write_table(self, rows):
        """Записывает данные в таблицу"""
        with open(self.table_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=self.headers)
            writer.writeheader()
            writer.writerows(rows)

    def update_row(self, prompt_id, updates):
        """Обновляет строку в таблице"""
        rows = self._read_table()
        for row in rows:
            if row['id'] == prompt_id:
                row.update(updates)
        self._write_table(rows)

    def get_prompt_status(self, prompt_id):
        """Получает статус промпта"""
        rows = self._read_table()
        for row in rows:
            if row['id'] == prompt_id:
                return row
        return None

    def get_pending_prompts(self):
        """Получает список необработанных промптов"""
        return [row for row in self._read_table() if row['status'] == 'pending']

    def mark_video_downloaded(self, prompt_id, model, video_path):
        """Отмечает, что видео загружено"""
        self.update_row(prompt_id, {
            'status': 'completed',
            'model': model,
            'video_path': video_path,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    def mark_error(self, prompt_id, model):
        """Отмечает ошибку при обработке промпта"""
        self.update_row(prompt_id, {
            'status': 'error',
            'model': model,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }) 