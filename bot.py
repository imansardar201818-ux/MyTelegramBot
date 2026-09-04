import telebot

# فقط یک توکن رو نگه دار (همون جدیدی که از بات‌فادر گرفتی)
TOKEN = "7234567890:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawE"
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "🚀 سلام! ربات با موفقیت راه‌اندازی شد!")

print("✅ ربات در حال اجراست...")
bot.polling()  # اینجا bot هست، نه bot_infinity
