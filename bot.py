import telebot

TOKEN = "8904951204:AAGsj8KhgcqbSKL7jkDVqa_70Oi8xlmFY5Y"  # توکن خودت رو بذار
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "🚀 سلام! ربات با موفقیت راه‌اندازی شد!")

print("✅ ربات در حال اجراست...")
bot.polling()
