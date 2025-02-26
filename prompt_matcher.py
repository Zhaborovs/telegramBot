import re
from difflib import SequenceMatcher

class PromptMatcher:
    def __init__(self):
        self.model_names = ['sora', 'hailuo', 'runway', 'kling', 'pika']
        
    def get_normalized_prompt(self, text):
        """Приводит промпт к формату, используемому в имени файла"""
        if not text:
            return ""
        
        # Приводим к нижнему регистру и берем первые 4 слова
        words = text.lower().split()[:4]
        text = ' '.join(words)
        
        # Заменяем все пробелы и спецсимволы на подчеркивание
        text = ''.join(c if c.isalnum() else '_' for c in text)
        # Убираем множественные подчеркивания
        text = '_'.join(part for part in text.split('_') if part)
        
        return text

    def extract_file_parts(self, filename):
        """Извлекает компоненты из имени файла"""
        parts = filename.lower().split('_')  # Приводим к нижнему регистру
        
        timestamp = None
        model = None
        prompt_start = 0
        
        # Ищем timestamp и модель
        for i, part in enumerate(parts):
            if part.isdigit() and len(part) in [8, 6]:
                timestamp = part
                prompt_start = i + 1
            elif part.lower() in self.model_names:
                model = part
                prompt_start = i + 1
                
        # Получаем промпт (все оставшиеся части)
        prompt = '_'.join(parts[prompt_start:]).replace('.mp4', '')
        
        return timestamp, model, prompt

    def is_matching(self, filename, expected_prompt):
        """Определяет, соответствует ли файл ожидаемому промпту"""
        if not filename or not expected_prompt:
            return False
            
        # Получаем компоненты из имени файла
        _, _, file_prompt = self.extract_file_parts(filename)
        
        # Нормализуем ожидаемый промпт
        norm_expected = self.get_normalized_prompt(expected_prompt)
        
        print("\nСравнение промптов:")
        print(f"Из файла: {file_prompt}")
        print(f"Ожидаемый (нормализованный): {norm_expected}")
        
        # Сравниваем, игнорируя регистр
        return norm_expected.lower() in file_prompt.lower() 