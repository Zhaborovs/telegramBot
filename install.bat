@echo off
title Установка Telegram бота
color 0B
cls

echo =========================================
echo    Установка Telegram бота
echo =========================================
echo.

REM Проверка Python
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo [91m✗ Python не найден. Пожалуйста, установите Python 3.10 или новее.[0m
    echo.
    echo Загрузите Python с официального сайта:
    echo https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

REM Запуск скрипта установки
echo [94m>> Запуск установки...[0m
echo.

python setup.py

if %errorlevel% neq 0 (
    echo.
    echo [91m✗ Установка завершилась с ошибкой.[0m
    pause
    exit /b 1
)

echo.
echo [92m✓ Установка успешно завершена![0m
echo.
pause 