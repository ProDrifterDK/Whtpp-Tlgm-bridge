import asyncio
from playwright.async_api import async_playwright
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage

HEADLESS = False
TELEGRAM_TOKEN = 'TU_TOKEN_DE_TELEGRAM'
TELEGRAM_CHAT_ID = 'TU_ID_DE_CHAT_DE_TELEGRAM'

# Selectors for WhatsApp Web
SEARCH_BOX = "[data-testid='chat-list-search']"
CHAT_RESULT = "[data-testid='chat-list-item']"
MESSAGE_INPUT = "[contenteditable='true'][title='Type a message']"
SEND_BUTTON = "button[aria-label='Send']"

state_map = {}
message_queue = asyncio.Queue()
account_ids = ['WhatsApp-1', 'WhatsApp-2']
user_data_dirs = ['./user_data/wa_profile_1', './user_data/wa_profile_2']

async def whatsapp_listener(account_id, user_data_dir, response_queue):
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir,
            headless=HEADLESS,
            args=["--disable-notifications"]
        )
        page = await browser.new_page()
        await page.goto('https://web.whatsapp.com/')
        
        await page.wait_for_selector('[data-testid="conversation-list"]', state='attached')
        
        while True:
            try:
                response_msg = response_queue.get_nowait()
                # Playwright steps to send message
                await page.locator(SEARCH_BOX).fill(response_msg["chat_target"])
                await page.locator(CHAT_RESULT).first.click()
                await page.locator(MESSAGE_INPUT).fill(response_msg["text"])
                await page.locator(SEND_BUTTON).click()
            except asyncio.QueueEmpty:
                pass

            try:
                new_msg_selector = 'div[aria-label="Message list"] div[tabindex="-1"]:not([data-processed])'
                messages = await page.query_selector_all(new_msg_selector)
                if messages:
                    for msg in messages:
                        await msg.evaluate('node => node.setAttribute("data-processed", "true")')
                        sender_el = await msg.query_selector('[data-testid="conversation-info-header"] [title]')
                        if not sender_el:
                            continue

                        sender = await sender_el.get_attribute('title')
                        msg_text_el = await msg.query_selector('[data-testid="msg-container"] div.selectable-text')
                        msg_text = await msg_text_el.inner_text() if msg_text_el else '<media>'

                        formatted = f'[{account_id}] De {sender}: {msg_text}'
                        await message_queue.put(('whatsapp', formatted, account_id, sender))
            except Exception as e:
                print(f"Error in WhatsApp listener ({account_id}): {str(e)}")
                await asyncio.sleep(5)

            # Short sleep to prevent CPU overload
            await asyncio.sleep(0.1)

async def telegram_bot_main(response_queues):
    bot = Bot(token=TELEGRAM_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(bot, storage=storage)
    
    @dp.message_handler()
    async def handle_message(message: types.Message):
        if message.reply_to_message and message.reply_to_message.message_id in state_map:
            state = state_map[message.reply_to_message.message_id]
            response_msg = {
                "chat_target": state["chat_original"],
                "text": message.text
            }
            await response_queues[state["account"]].put(response_msg)
        else:
            await message.reply("Por favor responde a un mensaje para enviar la respuesta.")
    
    async def queue_consumer():
        while True:
            source, content, account_id, chat_original = await message_queue.get()
            if source == 'whatsapp':
                sent_msg = await bot.send_message(TELEGRAM_CHAT_ID, content, reply_markup=None)
                state_map[sent_msg.message_id] = {
                    'account': account_id,
                    'chat_original': chat_original
                }
    
    await asyncio.gather(
        dp.start_polling(),
        queue_consumer()
    )

async def main():
    response_queues = {
        "WhatsApp-1": asyncio.Queue(),
        "WhatsApp-2": asyncio.Queue()
    }
    tasks = []
    for i, account_id in enumerate(account_ids):
        tasks.append(asyncio.create_task(whatsapp_listener(account_id, user_data_dirs[i], response_queues[account_id])))
    tasks.append(asyncio.create_task(telegram_bot_main(response_queues)))
    
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())