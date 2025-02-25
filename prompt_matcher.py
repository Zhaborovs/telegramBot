import re
from difflib import SequenceMatcher

class PromptMatcher:
    def __init__(self):
        self.model_names = ['sora', 'hailuo', 'runway', 'kling', 'pika']
        
        # Шаблоны для извлечения промптов из сообщений
        self.patterns = [
            r'отправлен промпт:\s*(.*)',
            r'используем промпт:\s*(.*)',
            r'получен промпт:\s*(.*)',
            r'промпт:\s*(.*)',
            r'задание:\s*(.*)',
            r'ваш промпт:\s*(.*)',
            r'видео для промпта:\s*(.*)'
        ]
        
        # Исключаемые слова при сравнении (предлоги, союзы, т.д.)
        self.stopwords = set([
            'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'with', 'by', 'from', 'of', 'as', 'в', 'на', 'с', 'из', 'от', 'к', 'по',
            'для', 'и', 'или', 'но', 'а', 'у', 'о', 'про', 'через', 'над', 'под'
        ])

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

    def extract_prompt(self, text):
        """Извлекает промпт из текста сообщения"""
        for pattern in self.patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        # Если не нашли по шаблонам, возвращаем оригинальный текст
        return text.strip()

    def find_prompt_in_message(self, prompt, message_text):
        """Проверяет, содержится ли промпт в сообщении"""
        # Нормализуем тексты для сравнения
        prompt_norm = prompt.lower().strip()
        message_norm = message_text.lower().strip()
        
        # Прямое сравнение
        if prompt_norm in message_norm:
            return True
            
        # Обработка ключевых фраз промпта
        prompt_words = set(w for w in re.findall(r'\w+', prompt_norm) if w not in self.stopwords and len(w) > 3)
        message_words = set(re.findall(r'\w+', message_norm))
        
        # Проверка наличия большинства ключевых слов
        common_words = prompt_words.intersection(message_words)
        if len(common_words) >= len(prompt_words) * 0.6:  # 60% совпадение
            return True
            
        return False
        
    def calculate_similarity(self, prompt, message_text):
        """Вычисляет степень сходства между промптом и сообщением (от 0 до 1)"""
        # Нормализуем тексты
        prompt_norm = prompt.lower().strip()
        message_norm = message_text.lower().strip()
        
        # Проверка на прямое включение
        if prompt_norm in message_norm:
            return 0.9  # Почти полное совпадение
            
        # Извлекаем промпт из сообщения, если он там есть
        extracted_prompt = self.extract_prompt(message_norm)
        
        # Вычисляем соотношение для полных строк
        ratio = SequenceMatcher(None, prompt_norm, extracted_prompt).ratio()
        
        # Обработка по словам
        prompt_words = [w for w in re.findall(r'\b\w+\b', prompt_norm) if w not in self.stopwords and len(w) > 3]
        message_words = [w for w in re.findall(r'\b\w+\b', message_norm) if w not in self.stopwords and len(w) > 3]
        
        # Проверка количества общих слов
        if not prompt_words or not message_words:
            return ratio  # Возвращаем только соотношение строк
            
        common_words = set(prompt_words).intersection(set(message_words))
        word_ratio = len(common_words) / max(len(prompt_words), 1)
        
        # Вычисляем средневзвешенное значение
        combined_ratio = (ratio * 0.4 + word_ratio * 0.6)
        
        # Проверяем наличие первых нескольких слов промпта
        if len(prompt_words) >= 3 and len(message_words) >= 3:
            first_words_match = set(prompt_words[:3]).intersection(set(message_words[:5]))
            if len(first_words_match) >= 2:
                combined_ratio += 0.1  # Бонус за совпадение начала
                
        return min(combined_ratio, 1.0)  # Максимум 1.0
            
    def get_prompt_hash(self, prompt):
        """Создает хеш для промпта (используется для базового определения промпта)"""
        # Нормализуем для хеширования
        norm_prompt = ' '.join(
            w for w in re.findall(r'\b\w+\b', prompt.lower())
            if w not in self.stopwords and len(w) > 2
        )
        
        # Простой хеш из первых и последних слов
        words = norm_prompt.split()
        if len(words) <= 5:
            hash_words = words
        else:
            hash_words = words[:3] + words[-2:]
            
        return ' '.join(hash_words) 