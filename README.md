# 🤖 Pomoshotru_bot — Telegram AI Bot на Google Gemini

Мощный Telegram-бот с искусственным интеллектом на базе **Google Gemini 3.6 Flash & Gemini Pro**.

---

## ✨ Возможности
* 🧠 **Умный диалог:** ответы на любые вопросы, поддержка контекста до 20 сообщений.
* 📷 **Анализ фото и скриншотов:** распознавание текста, решение задач, объяснение кода с картинок.
* 🎭 **4 Режима работы:**
  * 🤖 *Универсальный помощник*
  * 💻 *Senior Программист*
  * 🇬🇧 *Репетитор английского*
  * ⚡ *Краткая выжимка (TL;DR)*
* 🚀 **Подсветка кода и Markdown.**
* 🔄 Команда `/reset` для очистки истории диалога.

---

## 💻 Локальный запуск на компьютере
1. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```
2. Запустите бота:
   ```bash
   python bot.py
   ```
   *Или просто дважды кликните по файлу `start_bot.bat`.*

---

## 🌐 Бесплатный хостинг 24/7 через GitHub и Render.com

1. **Загрузите проект на GitHub:**
   * Создайте новый репозиторий на [GitHub.com](https://github.com/new) (например `pomoshotru_bot`).
   * В папке проекта выполните:
     ```bash
     git init
     git add .
     git commit -m "Initial commit"
     git branch -M main
     git remote add origin https://github.com/ВАШ_ЛОГИН/pomoshotru_bot.git
     git push -u origin main
     ```

2. **Запустите 24/7 бесплатно на [Render.com](https://render.com):**
   * Зарегистрируйтесь на Render через свой аккаунт GitHub.
   * Нажмите **New +** ➔ **Background Worker** (или **Web Service**).
   * Выберите ваш репозиторий `pomoshotru_bot`.
   * **Build Command:** `pip install -r requirements.txt`
   * **Start Command:** `python bot.py`
   * Нажмите **Create Service** — бот запустится и будет работать в облаке 24/7 бесплатно!
