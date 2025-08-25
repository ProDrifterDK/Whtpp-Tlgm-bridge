import asyncio
import os
from playwright.async_api import async_playwright
from aiogram import Bot, Dispatcher, types
from aiogram.types import ContentType
from dotenv import load_dotenv
from aiogram.filters import Command
from aiogram import F

# Load environment variables
load_dotenv()

# Replace hardcoded values
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
HEADLESS = os.getenv("HEADLESS", "False").lower() in ("true", "1", "yes")

# Selectors for WhatsApp Web
SEARCH_BOX = "div[aria-placeholder='Buscar un chat o iniciar uno nuevo']"
CHAT_RESULT = "div[aria-label='Lista de chats'] div[role='listitem']"
MESSAGE_INPUT = "div[aria-placeholder='Escribe un mensaje']"
SEND_BUTTON = "button[data-tab='11']"
ATTACH_BUTTON = "button[data-tab='10'][title='Adjuntar']"
PHOTO_BUTTON = "button[aria-label*='Fotos y videos'], [data-icon='image']"
DOCUMENT_BUTTON = "button[aria-label*='Documento'], [data-icon='document']"

state_map = {}
message_queue = asyncio.Queue()
account_ids = ['WhatsApp-1', 'WhatsApp-2']
user_data_dirs = ['./user_data/wa_profile_1', './user_data/wa_profile_2']

async def whatsapp_listener(account_id, user_data_dir, response_queue):
    async with async_playwright() as p:
        # Enhanced browser configuration to bypass WhatsApp Web browser compatibility checks
        browser_args = [
            "--disable-notifications",
            "--disable-blink-features=AutomationControlled",
            "--disable-web-security",
            "--disable-features=VizDisplayCompositor",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-field-trial-config",
            "--disable-back-forward-cache",
            "--disable-ipc-flooding-protection"
        ]
        
        browser = await p.chromium.launch_persistent_context(
            user_data_dir,
            headless=HEADLESS,
            args=browser_args,
            viewport={'width': 1366, 'height': 768},
            # Use a current Chrome user agent that WhatsApp Web recognizes as compatible
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='es-ES',
            timezone_id='America/Santiago',
            # Extra properties to avoid detection
            java_script_enabled=True,
            bypass_csp=True
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
        
        # Enhanced page configuration to avoid detection and bypass compatibility checks
        await page.add_init_script("""
            // Remove webdriver property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            
            // Mock plugins to look like a real browser
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            
            // Set realistic language preferences
            Object.defineProperty(navigator, 'languages', {
                get: () => ['es-ES', 'es', 'en-US', 'en'],
            });
            
            // Mock chrome runtime to look like regular Chrome
            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {}
            };
            
            // Override the permissions API
            Object.defineProperty(navigator, 'permissions', {
                get: () => ({
                    query: () => Promise.resolve({ state: 'granted' })
                })
            });
        """)
        
        # Add logging to understand what's happening in headless mode
        print(f"[{account_id}] Starting WhatsApp Web initialization...")
        print(f"[{account_id}] Headless mode: {HEADLESS}")
        print(f"[{account_id}] User Agent configured: Chrome 120 (Windows 10)")
        
        try:
            # Navigate to WhatsApp Web with proper wait strategy
            print(f"[{account_id}] Navigating to WhatsApp Web...")
            response = await page.goto('https://web.whatsapp.com/', wait_until='networkidle', timeout=60000)
            if response:
                print(f"[{account_id}] Navigation response status: {response.status}")
            else:
                print(f"[{account_id}] Navigation completed (no response object)")
            
            # Wait for page to settle and load properly
            await asyncio.sleep(5)
            
            title = await page.title()
            url = page.url
            print(f"[{account_id}] Page title: '{title}'")
            print(f"[{account_id}] Current URL: {url}")
            
            # Check if we got the browser compatibility error
            update_chrome_text = await page.query_selector('text=UPDATE GOOGLE CHROME')
            if update_chrome_text:
                print(f"[{account_id}] ERROR: Still getting browser compatibility warning - user agent might not be working")
                # Take screenshot for debugging
                try:
                    screenshot_path = f"./debug_compatibility_error_{account_id}.png"
                    await page.screenshot(path=screenshot_path)
                    print(f"[{account_id}] Compatibility error screenshot saved: {screenshot_path}")
                except:
                    pass
                raise Exception("WhatsApp Web browser compatibility check failed - user agent not recognized")
            
            print(f"[{account_id}] Browser compatibility check passed - looking for chat interface...")
            
            # Wait for WhatsApp Web to fully initialize with robust selectors and retry logic
            chat_list_found = False
            max_retries = 3
            retry_count = 0
            
            while not chat_list_found and retry_count < max_retries:
                retry_count += 1
                print(f"[{account_id}] Attempt {retry_count}: Looking for chat interface...")
                
                # Try multiple selectors for chat list (some might be in different languages)
                fallback_selectors = [
                    '[aria-label="Lista de chats"]',     # Spanish
                    '[aria-label="Chat list"]',          # English
                    '[aria-label="Chats"]',              # Simple English
                    '[aria-label*="Lista"]',             # Contains "Lista"
                    '[aria-label*="chats"]',             # Contains "chats"
                    '[role="grid"]',                     # WhatsApp uses grid role for chat list
                    'div[data-testid="chat-list"]',      # Test ID selector
                    '#pane-side',                        # Side pane ID
                    'div[class*="chat-list"]'            # Class-based selector
                ]
                
                for i, selector in enumerate(fallback_selectors):
                    try:
                        print(f"[{account_id}] Trying selector {i+1}: {selector}")
                        await page.wait_for_selector(selector, state='attached', timeout=15000)
                        print(f"[{account_id}] SUCCESS: Found chat interface with selector: {selector}")
                        chat_list_found = True
                        break
                    except:
                        print(f"[{account_id}] Selector {i+1} failed: {selector}")
                        continue
                
                if not chat_list_found:
                    # Check if we're on QR code screen (authentication required)
                    qr_selectors = [
                        'canvas[aria-label="Scan me!"]',
                        '[data-testid="qr-code"]',
                        'div[data-ref="qr"]',
                        'canvas'
                    ]
                    
                    for qr_selector in qr_selectors:
                        if await page.query_selector(qr_selector):
                            print(f"[{account_id}] QR code detected - waiting for authentication (5 minutes max)...")
                            try:
                                await page.wait_for_selector('[aria-label="Lista de chats"]', state='attached', timeout=300000)
                                print(f"[{account_id}] Authentication successful - chat list found!")
                                chat_list_found = True
                                break
                            except:
                                print(f"[{account_id}] Authentication timeout - QR code not scanned in time")
                                break
                    
                    if not chat_list_found and retry_count < max_retries:
                        print(f"[{account_id}] Retrying in 10 seconds...")
                        await asyncio.sleep(10)
            
            if not chat_list_found:
                # Final diagnostic
                print(f"[{account_id}] DIAGNOSTIC: Taking screenshot and HTML dump for analysis...")
                try:
                    screenshot_path = f"./debug_final_{account_id}.png"
                    await page.screenshot(path=screenshot_path)
                    html_content = await page.content()
                    html_path = f"./debug_final_{account_id}.html"
                    with open(html_path, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    print(f"[{account_id}] Final debug files saved: {screenshot_path}, {html_path}")
                except:
                    pass
                raise Exception("Could not find chat interface after all retry attempts")
            
        except Exception as e:
            print(f"[{account_id}] ERROR during WhatsApp Web initialization: {str(e)}")
            print(f"[{account_id}] Current page title: {await page.title()}")
            print(f"[{account_id}] Current URL: {page.url}")
            raise e
        
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
                # NEW APPROACH: Look for chats with unread messages in the chat list
                print(f"[{account_id}] Checking for chats with unread messages...")
                
                # ENHANCED APPROACH: Find chats with unread messages using actual WhatsApp Web structure
                unread_chat_items = await page.query_selector_all('[role="listitem"]')
                
                found_unread_chats = []
                for chat_item in unread_chat_items:
                    try:
                        # Check if this chat has unread message indicators
                        unread_indicators = [
                            'span[aria-label*="mensajes no leídos"]',
                            'span[aria-label*="mensaje no leído"]',
                            'span[aria-label*="unread message"]',
                            'div._ahlk.x1rg5ohu.xf6vk7d.xhslqc4.x16dsc37.xt4ypqs.x2b8uid', # Badge container
                            'div._ak72.false.false._ak73._ak7n._asiw._ap1-._ap1_' # Chat with unread class
                        ]
                        
                        unread_element = None
                        unread_count_text = None
                        
                        for indicator_selector in unread_indicators:
                            unread_element = await chat_item.query_selector(indicator_selector)
                            if unread_element:
                                # Try to get unread count from aria-label
                                unread_count_text = await unread_element.get_attribute('aria-label')
                                if unread_count_text and ('mensaje' in unread_count_text or 'unread' in unread_count_text):
                                    break
                        
                        if not unread_element or not unread_count_text:
                            continue
                            
                        # Get sender name from chat item using multiple strategies
                        sender_name = "Unknown"
                        sender_selectors = [
                            'span[title]:not([title=""])',
                            'span.x1iyjqo2.x6ikm8r.x10wlt62.x1n2onr6.xlyipyv.xuxw1ft.x1rg5ohu.x1jchvi3.xjb2p0i.xo1l8bm.x17mssa0.x1ic7a3i._ao3e',
                            'div._ak8q span[dir="auto"]'
                        ]
                        
                        for sender_selector in sender_selectors:
                            sender_name_el = await chat_item.query_selector(sender_selector)
                            if sender_name_el:
                                title = await sender_name_el.get_attribute('title')
                                if title and title.strip():
                                    sender_name = title.strip()
                                    break
                                else:
                                    text = await sender_name_el.inner_text()
                                    if text and text.strip():
                                        sender_name = text.strip()
                                        break
                        
                        found_unread_chats.append({
                            'chat_item': chat_item,
                            'sender_name': sender_name,
                            'unread_count_text': unread_count_text
                        })
                        
                    except Exception as chat_scan_error:
                        continue
                
                print(f"[{account_id}] Found {len(found_unread_chats)} chats with unread messages")
                
                # Add delay based on whether unread messages were found
                if len(found_unread_chats) == 0:
                    # No unread messages - longer delay to reduce CPU usage
                    print(f"[{account_id}] No unread messages, waiting 3 seconds before next check...")
                    await asyncio.sleep(3)
                else:
                    # Found unread messages - shorter delay for responsiveness
                    print(f"[{account_id}] Processing {len(found_unread_chats)} chats with unread messages...")
                    await asyncio.sleep(0.5)
                
                for chat_info in found_unread_chats:
                    try:
                        chat_item = chat_info['chat_item']
                        sender_name = chat_info['sender_name']
                        unread_count_text = chat_info['unread_count_text']
                        
                        print(f"[{account_id}] Processing chat from {sender_name} with {unread_count_text}")
                        
                        # Click on the chat to open it
                        print(f"[{account_id}] 🔄 CLICKING into chat: {sender_name}")
                        await chat_item.click()
                        print(f"[{account_id}] 🔄 Chat clicked, waiting for load...")
                        await asyncio.sleep(4)  # Increased wait time for chat to load
                        
                        # DIAGNOSTIC: Check if we're actually in a chat now
                        current_url = page.url
                        print(f"[{account_id}] 📍 Current URL after click: {current_url}")
                        
                        # CRUCIAL: Scroll to bottom to see latest messages
                        print(f"[{account_id}] ⬇️ Scrolling to bottom to see latest messages...")
                        try:
                            await page.evaluate('''() => {
                                const messageArea = document.querySelector('#main [data-testid="conversation-panel-messages"]') ||
                                                  document.querySelector('#main div[role="application"]') ||
                                                  document.querySelector('#main');
                                if (messageArea) {
                                    messageArea.scrollTop = messageArea.scrollHeight;
                                }
                            }''')
                            await asyncio.sleep(2)  # Wait for scroll and message load
                            print(f"[{account_id}] ✅ Scrolled to bottom")
                        except Exception as scroll_error:
                            print(f"[{account_id}] ⚠️ Could not scroll: {scroll_error}")
                        
                        # DIAGNOSTIC: Take screenshot to see current state
                        try:
                            safe_sender_name = (sender_name or 'Unknown').replace(' ', '_').replace('/', '_')
                            await page.screenshot(path=f"./debug_after_scroll_{account_id}_{safe_sender_name}.png")
                            print(f"[{account_id}] 📸 Screenshot saved after scrolling")
                        except:
                            pass
                        
                        # Now look for new messages in the opened chat
                        # Look for messages in the chat area (right side) - UPDATED BASED ON REAL HTML
                        print(f"[{account_id}] 🔍 SEARCHING for message area...")
                        message_area_selectors = [
                            '#main',  # Main chat container
                            'div[id="main"]',  # Main div with id
                            '[data-testid="conversation-panel-messages"]',
                            '[data-testid="conversation-panel"]',
                            'div[role="application"]',
                            'div[aria-label="Mensajes"]',
                            'div[aria-label="Messages"]'
                        ]
                        
                        message_area = None
                        for i, selector in enumerate(message_area_selectors):
                            try:
                                print(f"[{account_id}] 🔍 Trying message area selector {i+1}: {selector}")
                                message_area = await page.query_selector(selector)
                                if message_area:
                                    print(f"[{account_id}] ✅ SUCCESS: Found message area with selector: {selector}")
                                    break
                                else:
                                    print(f"[{account_id}] ❌ Selector {i+1} returned null")
                            except Exception as sel_error:
                                print(f"[{account_id}] ❌ Selector {i+1} failed with error: {sel_error}")
                                continue
                                
                        if not message_area:
                            print(f"[{account_id}] ❌ CRITICAL: Could not find message area for chat {sender_name}")
                            # DIAGNOSTIC: Log all available elements in #main
                            try:
                                main_elements = await page.query_selector_all('#main *')
                                print(f"[{account_id}] 📋 Found {len(main_elements)} elements in #main")
                                # Get some sample elements for debugging
                                for i, elem in enumerate(main_elements[:5]):
                                    try:
                                        tag_name = await elem.evaluate('el => el.tagName')
                                        class_name = await elem.get_attribute('class') or 'no-class'
                                        test_id = await elem.get_attribute('data-testid') or 'no-testid'
                                        print(f"[{account_id}] 📋 Element {i+1}: <{tag_name}> class='{class_name}' testid='{test_id}'")
                                    except:
                                        pass
                            except:
                                pass
                            continue
                            
                        # Get recent messages from the chat - BASED ON REAL WHATSAPP STRUCTURE
                        print(f"[{account_id}] 🔍 SEARCHING for RECENT/UNREAD messages in message area...")
                        
                        # REAL WHATSAPP SELECTORS: Based on the actual HTML structure provided
                        recent_messages_selectors = [
                            # Actual WhatsApp message containers (incoming messages)
                            'div[data-testid="msg-container"]',
                            'div[role="row"]',  # Messages use role="row"
                            '[data-pre-plain-text]',  # Messages with pre-plain-text
                            # Broader message detection
                            'div[class*="_ak72"]',  # Message wrapper class from HTML
                            'div[class*="message"]',
                            # Fallback selectors
                            'div:has(span.selectable-text)',
                            'div:has(.copyable-text)'
                        ]
                        
                        recent_messages = []
                        for i, msg_selector in enumerate(recent_messages_selectors):
                            try:
                                print(f"[{account_id}] 🔍 Trying message selector {i+1}: {msg_selector}")
                                messages = await message_area.query_selector_all(msg_selector)
                                print(f"[{account_id}] 📊 Found {len(messages)} messages with selector {i+1}")
                                if messages:
                                    # Extract number from unread_count_text safely
                                    unread_count = 3  # default
                                    if unread_count_text:
                                        parts = unread_count_text.split()
                                        if parts and parts[0].isdigit():
                                            unread_count = int(parts[0])
                                    recent_messages = messages[-unread_count:]  # Get recent unread messages
                                    print(f"[{account_id}] ✅ SUCCESS: Selected {len(recent_messages)} recent messages (unread count: {unread_count})")
                                    break
                                else:
                                    print(f"[{account_id}] ❌ No messages found with selector {i+1}")
                            except Exception as msg_error:
                                print(f"[{account_id}] ❌ Message selector {i+1} failed: {msg_error}")
                                continue
                                
                        if not recent_messages:
                            print(f"[{account_id}] ⚠️ No messages found with primary selectors, trying aggressive fallback...")
                            # AGGRESSIVE FALLBACK: get all messages and take the most recent ones
                            all_message_selectors = [
                                # Try different approaches to find ANY messages
                                'div[data-testid*="msg"]',
                                '[role="row"]',
                                'div[class*="message"]',
                                'div[class*="Message"]',
                                '[class*="copyable-text"]',
                                'span[dir="ltr"]',  # Text spans
                                'span[dir="auto"]', # Auto-direction spans
                                '#main div > div > div',  # Deep nested divs
                                '#main [data-testid="conversation-panel-messages"] > div',
                                '#main [data-testid="conversation-panel-messages"] *'
                            ]
                            
                            for i, msg_selector in enumerate(all_message_selectors):
                                try:
                                    print(f"[{account_id}] 🔄 Aggressive fallback selector {i+1}: {msg_selector}")
                                    all_messages = await message_area.query_selector_all(msg_selector)
                                    print(f"[{account_id}] 📊 Aggressive fallback found {len(all_messages)} total elements")
                                    if len(all_messages) > 0:
                                        # Get more recent messages based on unread count
                                        unread_count = 5  # Default to get more messages
                                        if unread_count_text:
                                            parts = unread_count_text.split()
                                            if parts and parts[0].isdigit():
                                                unread_count = max(int(parts[0]), 3)  # At least 3, but use unread count if higher
                                        recent_messages = all_messages[-unread_count:]  # Get last N messages
                                        print(f"[{account_id}] ✅ AGGRESSIVE FALLBACK SUCCESS: got {len(recent_messages)} recent messages")
                                        break
                                    else:
                                        print(f"[{account_id}] ❌ Aggressive fallback selector {i+1} returned no elements")
                                except Exception as fallback_error:
                                    print(f"[{account_id}] ❌ Aggressive fallback selector {i+1} failed: {fallback_error}")
                                    continue
                        
                        # Process each recent message
                        print(f"[{account_id}] 📝 PROCESSING {len(recent_messages)} messages...")
                        for msg_index, msg in enumerate(recent_messages):
                            try:
                                print(f"[{account_id}] 📝 Processing message {msg_index + 1}/{len(recent_messages)}")
                                
                                # Mark as processed
                                await msg.evaluate('node => node.setAttribute("data-processed", "true")')
                                print(f"[{account_id}] ✅ Message {msg_index + 1} marked as processed")
                                
                                # Get message text
                                print(f"[{account_id}] 🔍 Extracting text from message {msg_index + 1}...")
                                text_selectors = [
                                    # REAL WhatsApp Web selectors based on HTML structure provided
                                    'span.x1iyjqo2.x6ikm8r.x10wlt62.x1n2onr6.xlyipyv.xuxw1ft.x1rg5ohu._ao3e',  # Actual text span class
                                    'span.selectable-text',  # Common text class
                                    'span[dir="ltr"]',      # Direction-based (most messages)
                                    'span[dir="auto"]',     # Auto-direction text
                                    
                                    # Based on HTML structure patterns
                                    'div._ak8k span',       # Message content area
                                    'span.x78zum5.x1cy8zhl span', # Message text container
                                    '.copyable-text span',
                                    '.copyable-text',
                                    
                                    # Fallback for any text spans
                                    'span:not([class*="icon"]):not([aria-hidden="true"]):not([class*="emoji"])',
                                    'div > span:not([class*="icon"]):not([aria-hidden])'
                                ]
                                
                                msg_text = None
                                for j, text_selector in enumerate(text_selectors):
                                    try:
                                        print(f"[{account_id}] 🔍 Trying text selector {j+1}: {text_selector}")
                                        text_el = await msg.query_selector(text_selector)
                                        if text_el:
                                            msg_text = await text_el.inner_text()
                                            print(f"[{account_id}] 📄 Text selector {j+1} returned: '{msg_text[:30]}...' (length: {len(msg_text) if msg_text else 0})")
                                            if msg_text and msg_text.strip():
                                                print(f"[{account_id}] ✅ SUCCESS: Found valid message text with selector {j+1}")
                                                break
                                        else:
                                            print(f"[{account_id}] ❌ Text selector {j+1} returned null element")
                                    except Exception as text_error:
                                        print(f"[{account_id}] ❌ Text selector {j+1} failed: {text_error}")
                                        continue
                                
                                if msg_text and msg_text.strip():
                                    print(f"[{account_id}] ✅ FOUND MESSAGE from {sender_name}: {msg_text[:50]}...")
                                    message_data = {
                                        "type": "text",
                                        "text": f'[{account_id}] De {sender_name}: {msg_text}',
                                        "account_id": account_id,
                                        "sender": sender_name
                                    }
                                    print(f"[{account_id}] 📤 [QUEUE] Adding message to queue: {message_data}")
                                    await message_queue.put(('whatsapp', message_data))
                                    print(f"[{account_id}] 📤 [QUEUE] ✅ Message added to queue successfully")
                                else:
                                    print(f"[{account_id}] ❌ FAILED to extract text from message {msg_index + 1}")
                                    # DIAGNOSTIC: Log message element structure
                                    try:
                                        outer_html = await msg.evaluate('el => el.outerHTML')
                                        print(f"[{account_id}] 🔬 Message {msg_index + 1} HTML structure: {outer_html[:200]}...")
                                    except:
                                        pass
                                    
                            except Exception as msg_error:
                                print(f"[{account_id}] ❌ Error processing individual message {msg_index + 1}: {msg_error}")
                                continue
                        
                        # Go back to chat list after processing
                        print(f"[{account_id}] 🔙 Navigating back to chat list...")
                        # Try to click back button or use ESC key
                        back_selectors = [
                            'button[aria-label*="Atrás"]',
                            'button[aria-label*="Back"]',
                            'header button[data-testid="back"]',
                            'header button[data-icon="back"]',
                            'button[data-testid="back"]'
                        ]
                        
                        back_clicked = False
                        for i, back_selector in enumerate(back_selectors):
                            try:
                                print(f"[{account_id}] 🔙 Trying back button selector {i+1}: {back_selector}")
                                back_btn = await page.query_selector(back_selector)
                                if back_btn:
                                    await back_btn.click()
                                    back_clicked = True
                                    print(f"[{account_id}] ✅ Successfully clicked back button with selector {i+1}")
                                    break
                                else:
                                    print(f"[{account_id}] ❌ Back button selector {i+1} returned null")
                            except Exception as back_error:
                                print(f"[{account_id}] ❌ Back button selector {i+1} failed: {back_error}")
                                continue
                                
                        if not back_clicked:
                            print(f"[{account_id}] 🔙 No back button found, using ESC key...")
                            # Fallback: press ESC key
                            await page.keyboard.press('Escape')
                            print(f"[{account_id}] ⌨️ ESC key pressed")
                            
                        await asyncio.sleep(2)  # Increased wait for navigation
                        print(f"[{account_id}] ✅ Navigation back completed")
                        
                    except Exception as chat_error:
                        print(f"[{account_id}] Error processing chat: {chat_error}")
                        continue
                    
                    # Add delay between processing different chats to prevent overwhelming WhatsApp Web
                    await asyncio.sleep(1)
                        
            except Exception as e:
                print(f"[{account_id}] Error in message processing: {str(e)}")
                await asyncio.sleep(5)

            # Main loop delay - reduced from 0.1 to prevent rapid polling
            # The delay is now handled above based on whether messages were found
            await asyncio.sleep(0.5)

async def telegram_bot_main(response_queues):
    bot = Bot(token=TELEGRAM_TOKEN)
    dp = Dispatcher(storage=None)
    
    @dp.message(Command(commands=["start", "help"]))
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
    
    @dp.message((F.photo) | (F.document))
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
        print("🚀 [QUEUE CONSUMER] Starting queue consumer...")
        while True:
            try:
                print("🔄 [QUEUE CONSUMER] Waiting for messages in queue...")
                source, content = await message_queue.get()
                print(f"📨 [QUEUE CONSUMER] Received message from {source}: {content}")
                
                if source == 'whatsapp':
                    if content["type"] == "text":
                        print(f"📤 [TELEGRAM] Sending text message to Telegram...")
                        try:
                            sent_msg = await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=content["text"])
                            state_map[sent_msg.message_id] = {
                                'account': content["account_id"],
                                'chat_original': content["sender"]
                            }
                            print(f"✅ [TELEGRAM] Text message sent successfully! Message ID: {sent_msg.message_id}")
                        except Exception as telegram_error:
                            print(f"❌ [TELEGRAM] Failed to send text message: {telegram_error}")
                            
                    elif content["type"] == "media":
                        print(f"📤 [TELEGRAM] Sending media message to Telegram...")
                        try:
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
                                print(f"✅ [TELEGRAM] Media message sent successfully! Message ID: {sent_msg.message_id}")
                            os.remove(content["file_path"])
                        except Exception as telegram_error:
                            print(f"❌ [TELEGRAM] Failed to send media message: {telegram_error}")
                            
                    elif content["type"] == "status":
                        print(f"📤 [TELEGRAM] Sending status message to Telegram...")
                        try:
                            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=content["text"])
                            print(f"✅ [TELEGRAM] Status message sent successfully!")
                        except Exception as telegram_error:
                            print(f"❌ [TELEGRAM] Failed to send status message: {telegram_error}")
                else:
                    print(f"⚠️ [QUEUE CONSUMER] Unknown message source: {source}")
                    
            except Exception as queue_error:
                print(f"❌ [QUEUE CONSUMER] Error processing queue message: {queue_error}")
                await asyncio.sleep(1)
    
    # Create downloads directory
    os.makedirs("./downloads", exist_ok=True)
    
    await asyncio.gather(
        dp.start_polling(bot),
        queue_consumer()
    )

async def main():
    print("🚀 [MAIN] Starting bridge application...")
    print(f"🚀 [MAIN] TELEGRAM_TOKEN configured: {'Yes' if TELEGRAM_TOKEN else 'No'}")
    print(f"🚀 [MAIN] TELEGRAM_CHAT_ID: {TELEGRAM_CHAT_ID}")
    
    response_queues = {
        "WhatsApp-1": asyncio.Queue(),
        "WhatsApp-2": asyncio.Queue()
    }
    tasks = []
    
    # Start WhatsApp listeners
    print("🚀 [MAIN] Starting WhatsApp listeners...")
    for i, account_id in enumerate(account_ids):
        tasks.append(asyncio.create_task(whatsapp_listener(account_id, user_data_dirs[i], response_queues[account_id])))
    
    # Start Telegram bot with error handling
    print("🚀 [MAIN] Starting Telegram bot...")
    try:
        telegram_task = asyncio.create_task(telegram_bot_main(response_queues))
        tasks.append(telegram_task)
        print("🚀 [MAIN] Telegram bot task created successfully")
    except Exception as telegram_error:
        print(f"🚀 [MAIN] ERROR creating Telegram bot task: {telegram_error}")
        raise telegram_error
    
    print("🚀 [MAIN] All tasks created, starting execution...")
    try:
        await asyncio.gather(*tasks)
    except Exception as gather_error:
        print(f"🚀 [MAIN] ERROR in task execution: {gather_error}")
        raise gather_error

if __name__ == "__main__":
    asyncio.run(main())