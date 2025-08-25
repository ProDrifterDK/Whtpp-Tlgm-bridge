import asyncio
import os
from playwright.async_api import async_playwright
from aiogram import Bot, Dispatcher, types
from aiogram.types import ContentType
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Replace hardcoded values
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
HEADLESS = os.getenv("HEADLESS", "False").lower() in ("true", "1", "yes")

# Selectors for WhatsApp Web
SEARCH_BOX = "[data-testid='chat-list-search']"
CHAT_RESULT = "[data-testid='chat-list-item']"
MESSAGE_INPUT = "[contenteditable='true'][title='Type a message']"
SEND_BUTTON = "button[aria-label='Send']"
ATTACH_BUTTON = "div[title='Attach']"
PHOTO_BUTTON = "li[data-testid='photo-video']"
DOCUMENT_BUTTON = "li[data-testid='document']"

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
        
        # Browser close handler
        def handle_close(browser_context):
            asyncio.create_task(
                message_queue.put(('status', {
                    "text": f"CRITICAL: {account_id} disconnected!"
                }))
            )
        browser.on("close", handle_close)
        
        page = await browser.new_page()
        await page.goto('https://web.whatsapp.com/')
        
        await page.wait_for_selector('[data-testid="conversation-list"]', state='attached')
        
        while True:
            try:
                response_msg = response_queue.get_nowait()
                if response_msg["type"] == "text":
                    await page.locator(SEARCH_BOX).fill(response_msg["chat_target"])
                    await page.locator(CHAT_RESULT).first.click()
                    await page.locator(MESSAGE_INPUT).fill(response_msg["text"])
                    await page.locator(SEND_BUTTON).click()
                elif response_msg["type"] == "media":
                    await page.locator(SEARCH_BOX).fill(response_msg["chat_target"])
                    await page.locator(CHAT_RESULT).first.click()
                    async with page.expect_file_chooser() as fc_info:
                        await page.locator(ATTACH_BUTTON).click()
                        await page.locator(DOCUMENT_BUTTON if response_msg["file_type"] == "document" else PHOTO_BUTTON).click()
                    file_chooser = await fc_info.value
                    await file_chooser.set_files(response_msg["file_path"])
                    await asyncio.sleep(0.5)
                    await page.locator(SEND_BUTTON).click()
                    os.remove(response_msg["file_path"])
            except asyncio.QueueEmpty:
                pass
            except Exception as e:
                print(f"Error sending message ({account_id}): {str(e)}")

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
                        
                        # Check for media
                        file_path = None
                        file_type = None
                        download_btn = None
                        if await msg.query_selector("img"):
                            file_type = "photo"
                            download_btn = await msg.query_selector("img")
                        elif await msg.query_selector("[data-testid='document']"):
                            file_type = "document"
                            download_btn = await msg.query_selector("[data-testid='document']")
                        
                        if download_btn:
                            async with page.expect_download() as download_info:
                                await download_btn.click()
                            download = await download_info.value
                            file_path = f"./downloads/{download.suggested_filename}"
                            await download.save_as(file_path)
                            
                            await message_queue.put(('whatsapp', {
                                "type": "media",
                                "file_path": file_path,
                                "file_type": file_type,
                                "account_id": account_id,
                                "sender": sender
                            }))
                        else:
                            msg_text = await msg_text_el.inner_text() if msg_text_el else '<media>'
                            await message_queue.put(('whatsapp', {
                                "type": "text",
                                "text": f'[{account_id}] De {sender}: {msg_text}',
                                "account_id": account_id,
                                "sender": sender
                            }))
            except Exception as e:
                print(f"Error processing message ({account_id}): {str(e)}")
                await asyncio.sleep(5)

            await asyncio.sleep(0.1)

async def telegram_bot_main(response_queues):
    bot = Bot(token=TELEGRAM_TOKEN)
    dp = Dispatcher(bot=bot, storage=None)
    
    @dp.message(commands=['start', 'help'])
    async def send_welcome(message: types.Message):
        await message.reply("Bienvenido al puente WhatsApp-Telegram. Responde a un mensaje para enviar una respuesta a WhatsApp.")
    
    @dp.message()
    async def handle_text(message: types.Message):
        if message.reply_to_message and message.reply_to_message.message_id in state_map:
            state = state_map[message.reply_to_message.message_id]
            response_msg = {
                "chat_target": state["chat_original"],
                "text": message.text,
                "type": "text"
            }
            await response_queues[state["account"]].put(response_msg)
        else:
            await message.reply("Por favor responde a un mensaje para enviar la respuesta.")
    
    @dp.message(content_types=[ContentType.PHOTO, ContentType.DOCUMENT])
    async def handle_media(message: types.Message):
        if message.reply_to_message and message.reply_to_message.message_id in state_map:
            state = state_map[message.reply_to_message.message_id]
            
            if message.photo:
                file_id = message.photo[-1].file_id
                file_type = "photo"
            elif message.document:
                file_id = message.document.file_id
                file_type = "document"
            else:
                return
            
            file = await bot.get_file(file_id)
            if not file.file_path:
                return  # Skip if no file path

            file_name = file.file_path.split('/')[-1]
            file_path = f"./downloads/{file_name}"
            await bot.download_file(file.file_path, destination=file_path)
            
            await response_queues[state["account"]].put({
                "type": "media",
                "file_path": file_path,
                "file_type": file_type,
                "chat_target": state["chat_original"]
            })
    
    async def queue_consumer():
        while True:
            source, content = await message_queue.get()
            if source == 'whatsapp':
                if content["type"] == "text":
                    sent_msg = await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=content["text"])
                    state_map[sent_msg.message_id] = {
                        'account': content["account_id"],
                        'chat_original': content["sender"]
                    }
                elif content["type"] == "media":
                    file = types.FSInputFile(content["file_path"])
                    sent_msg = None
                    if content["file_type"] == "photo":
                        sent_msg = await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=file)
                    elif content["file_type"] == "document":
                        sent_msg = await bot.send_document(chat_id=TELEGRAM_CHAT_ID, document=file)
                    
                    if sent_msg:
                        state_map[sent_msg.message_id] = {
                            'account': content["account_id"],
                            'chat_original': content["sender"]
                        }
                    os.remove(content["file_path"])
                elif content["type"] == "status":
                    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=content["text"])
    
    # Create downloads directory
    os.makedirs("./downloads", exist_ok=True)
    
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