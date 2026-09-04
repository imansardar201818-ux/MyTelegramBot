import telebot

TOKEN = "8904951204:AAF1UaBAzfD_OIrdqHiv8egIfs9a8g3ld4E"  7234567890:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawE
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "🚀 سلام! ربات با موفقیت راه‌اندازی شد!")

print("✅ ربات در حال اجراست...")
bot.polling()
