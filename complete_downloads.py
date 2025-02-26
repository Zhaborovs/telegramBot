import csv
import os
from datetime import datetime
import sys

def sanitize_filename(filename):
    """Удаляет недопустимые символы из имени файла"""
    import re
    return re.sub(r'[<>:"/\\|?*]', '_', filename)

def get_first_5_words(text):
    """Получаем первые 5 слов из текста"""
    words = text.split()[:5]
    return '_'.join(words)

def download_pending_videos():
    """Скачивает видео, помеченные как completed, но без путей к файлам"""
    base_path = 'downloaded_videos'
    table_file = os.path.join(base_path, 'prompts_table.csv')
    
    # Проверяем, существует ли файл таблицы
    if not os.path.exists(table_file):
        print(f"Ошибка: файл таблицы {table_file} не найден")
        return
    
    # Создаем директорию для скачиваний, если её нет
    if not os.path.exists(base_path):
        os.makedirs(base_path)
    
    # Читаем таблицу
    with open(table_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    # Находим строки со статусом "completed", но без пути к видео
    pending_downloads = []
    for row in rows:
        if row['status'] == 'completed' and not row['video_path']:
            pending_downloads.append(row)
    
    if not pending_downloads:
        print("Нет ожидающих загрузки видео")
        return
    
    print(f"Найдено {len(pending_downloads)} видео для загрузки:")
    
    # Выводим найденные видео
    for i, row in enumerate(pending_downloads, 1):
        prompt_text = row['prompt'][:40] + '...' if len(row['prompt']) > 40 else row['prompt']
        print(f"{i}. ID: {row['id']} - '{prompt_text}'")
    
    print("\nЭти видео отмечены как 'completed', но не имеют пути к файлу.")
    print("Скорее всего, программа завершилась до завершения скачивания.")
    print("\nЧтобы скачать видео, необходимо выполнить следующие действия:")
    print("1. Отправьте эти промпты боту вручную используя Telegram")
    print("2. После получения видео от бота, сохраните их в папку 'downloaded_videos'")
    print("3. Запустите этот скрипт снова с параметром --update, чтобы обновить таблицу")
    
    # Проверяем запущен ли скрипт с параметром --update
    if len(sys.argv) > 1 and sys.argv[1] == '--update':
        update_table(pending_downloads, rows, table_file)

def update_table(pending_downloads, all_rows, table_file):
    """Обновляет таблицу, добавляя пути к скачанным видео"""
    base_path = 'downloaded_videos'
    
    # Получаем список всех видео файлов в директории
    video_files = [f for f in os.listdir(base_path) if f.endswith('.mp4')]
    
    if not video_files:
        print("В директории downloaded_videos не найдено видео файлов")
        return
    
    # Обновляем пути для каждого ожидающего загрузки видео
    updated_count = 0
    
    for row in pending_downloads:
        prompt_id = row['id']
        model = row.get('model', '🌙 SORA')  # Используем SORA по умолчанию, если модель не указана
        
        # Ищем файл, который может соответствовать данному промпту
        matching_files = [f for f in video_files if prompt_id in f]
        
        if matching_files:
            # Если нашли, обновляем путь
            filepath = os.path.join(base_path, matching_files[0])
            for table_row in all_rows:
                if table_row['id'] == prompt_id:
                    table_row['video_path'] = filepath
                    updated_count += 1
                    break
        else:
            # Если не нашли, создаем имя на основе промпта и модели
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Очищаем строку модели от эмодзи и получаем короткое имя
            model_short = model.split()[0].replace('🌙', '').replace('➕', '').replace('📦', '')\
                        .replace('🎬', '').replace('🎯', '').replace('👁', '')\
                        .replace('🌫', '').replace('🦋', '').strip()
            
            # Создаем имя файла
            prompt_words = get_first_5_words(row['prompt'])
            prompt_words = sanitize_filename(prompt_words)
            filename = f"{timestamp}_{prompt_id}_{model_short}_{prompt_words}.mp4"
            
            print(f"Для промпта {prompt_id} не найдено скачанных видео")
            print(f"Предлагаемое имя файла: {filename}")
            
            # Спрашиваем пользователя о соответствии файла
            print("Доступные видео файлы:")
            for i, file in enumerate(video_files, 1):
                print(f"{i}. {file}")
            
            choice = input(f"Выберите номер файла для промпта {prompt_id} (или Enter для пропуска): ")
            
            if choice.strip() and choice.isdigit() and 1 <= int(choice) <= len(video_files):
                selected_file = video_files[int(choice) - 1]
                filepath = os.path.join(base_path, selected_file)
                
                for table_row in all_rows:
                    if table_row['id'] == prompt_id:
                        table_row['video_path'] = filepath
                        updated_count += 1
                        break
    
    # Сохраняем обновленную таблицу
    if updated_count > 0:
        with open(table_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=all_rows[0].keys())
            writer.writeheader()
            writer.writerows(all_rows)
        
        print(f"Обновлены пути к {updated_count} видео файлам")
    else:
        print("Не удалось обновить ни одну запись")

if __name__ == "__main__":
    download_pending_videos() 