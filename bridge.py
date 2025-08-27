import asyncio
import os
import json
import signal
from asyncio import Lock
from playwright.async_api import async_playwright
from aiogram import Bot, Dispatcher, types
from aiogram.types import ContentType
from dotenv import load_dotenv
from aiogram.filters import Command
from aiogram import F
from typing import Any

# Load environment variables
load_dotenv()

# Replace hardcoded values
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
HEADLESS = os.getenv("HEADLESS", "False").lower() in ("true", "1", "yes")

# Progress indicator system
PROGRESS_STATES = {
    "received": "📥 Message received from Telegram",
    "queued": "⏳ Message queued for WhatsApp processing",
    "processing": "⚙️ Processing message in WhatsApp",
    "searching": "🔍 Searching for chat recipient",
    "navigating": "🧭 Navigating to chat",
    "typing": "✍️ Typing message",
    "sending": "📤 Sending message to WhatsApp",
    "sent": "✅ Message successfully sent to WhatsApp",
    "forwarding": "🔄 Forwarding to Telegram",
    "completed": "🎉 Message processing completed",
    "error": "❌ Error occurred during processing"
}

# Progress message IDs storage (message_id -> progress_message_id)
progress_messages = {}
progress_lock = Lock()

async def send_progress_message(bot: Bot, chat_id: str, message_id: int, state: str, details: str = ""):
    """Send initial progress message to Telegram chat"""
    try:
        progress_text = f"{PROGRESS_STATES.get(state, 'Unknown state')}"
        if details:
            progress_text += f"\n{details}"

        async with progress_lock:
            progress_msg = await bot.send_message(
                chat_id=chat_id,
                text=progress_text,
                reply_to_message_id=message_id
            )
            progress_messages[message_id] = progress_msg.message_id

        print(f"📊 [PROGRESS] Sent progress message for {message_id}: {state}")
        return progress_msg.message_id

    except Exception as e:
        print(f"⚠️ [PROGRESS] Failed to send progress message: {e}")
        return None

async def update_progress_message(bot: Bot, chat_id: str, original_message_id: int, state: str, details: str = ""):
    """Update existing progress message with new state"""
    try:
        async with progress_lock:
            progress_message_id = progress_messages.get(original_message_id)
            if not progress_message_id:
                print(f"⚠️ [PROGRESS] No progress message found for {original_message_id}")
                return False

        progress_text = f"{PROGRESS_STATES.get(state, 'Unknown state')}"
        if details:
            progress_text += f"\n{details}"

        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=progress_message_id,
            text=progress_text
        )

        print(f"📊 [PROGRESS] Updated progress for {original_message_id}: {state}")

        # Clean up progress message ID if completed or errored
        if state in ["completed", "error"]:
            async with progress_lock:
                progress_messages.pop(original_message_id, None)

        return True

    except Exception as e:
        print(f"⚠️ [PROGRESS] Failed to update progress message: {e}")
        return False

async def cleanup_progress_message(bot: Bot, chat_id: str, original_message_id: int):
    """Clean up progress message from storage"""
    try:
        async with progress_lock:
            progress_messages.pop(original_message_id, None)
        print(f"🧹 [PROGRESS] Cleaned up progress tracking for {original_message_id}")
    except Exception as e:
        print(f"⚠️ [PROGRESS] Failed to cleanup progress message: {e}")

async def send_progress_update(telegram_message_id: int, state: str, details: str = ""):
    """Send progress update to the progress queue"""
    try:
        progress_data = {
            'telegram_message_id': telegram_message_id,
            'state': state,
            'details': details
        }
        await progress_queue.put(progress_data)
        print(f"📊 [PROGRESS] Queued progress update: {telegram_message_id} -> {state}")
    except Exception as e:
        print(f"⚠️ [PROGRESS] Failed to queue progress update: {e}")

# Selectors for WhatsApp Web
SEARCH_BOX = "div[aria-placeholder='Buscar un chat o iniciar uno nuevo']"
CHAT_RESULT = "div[aria-label='Lista de chats'] div[role='listitem']"
MESSAGE_INPUT = "div[aria-placeholder='Escribe un mensaje']"
SEND_BUTTON = "button[data-tab='11']"
ATTACH_BUTTON = "button[data-tab='10'][title='Adjuntar']"
PHOTO_BUTTON = "button[aria-label*='Fotos y videos'], [data-icon='image']"
DOCUMENT_BUTTON = "button[aria-label*='Documento'], [data-icon='document']"

# Persistent state map with disk storage
STATE_MAP_FILE = "./state_map.json"
STATE_MAP_BACKUP_DIR = "./state_backups"
MAX_BACKUP_FILES = 10  # Keep maximum 10 backup files

def load_state_map():
    """Load state_map from disk or create empty one with enhanced error handling"""
    try:
        print(f"🐛 [STATE DEBUG] Checking if {STATE_MAP_FILE} exists...")
        if os.path.exists(STATE_MAP_FILE):
            print(f"🐛 [STATE DEBUG] File exists, attempting to load...")

            # Check file size to detect potentially empty/corrupted files
            file_size = os.path.getsize(STATE_MAP_FILE)
            if file_size == 0:
                print(f"⚠️ [STATE] File {STATE_MAP_FILE} is empty, creating new state_map")
                return {}

            try:
                with open(STATE_MAP_FILE, 'r', encoding='utf-8') as f:
                    loaded_state = json.load(f)
                    print(f"🐛 [STATE DEBUG] Raw loaded data keys: {list(loaded_state.keys())}")

                    # Validate loaded data structure
                    if not isinstance(loaded_state, dict):
                        raise ValueError(f"Expected dict, got {type(loaded_state)}")

                    # Convert string keys back to integers (JSON saves as strings)
                    state_map = {}
                    for k, v in loaded_state.items():
                        try:
                            int_key = int(k)
                            state_map[int_key] = v
                        except (ValueError, TypeError) as key_error:
                            print(f"⚠️ [STATE] Skipping invalid key '{k}': {key_error}")
                            continue

                    print(f"🔄 [STATE] Loaded {len(state_map)} entries from {STATE_MAP_FILE}")
                    print(f"🔄 [STATE] Loaded message IDs: {list(state_map.keys())}")
                    return state_map

            except json.JSONDecodeError as json_error:
                print(f"❌ [STATE] JSON decode error in {STATE_MAP_FILE}: {json_error}")
                print(f"📁 [STATE] File size: {file_size} bytes")
                # Try to read first few lines for debugging
                try:
                    with open(STATE_MAP_FILE, 'r', encoding='utf-8') as f:
                        first_lines = ''.join(f.readline() for _ in range(3))
                        print(f"📄 [STATE] First lines of file: {repr(first_lines)}")
                except:
                    pass
                return {}

            except (UnicodeDecodeError, IOError) as file_error:
                print(f"❌ [STATE] File read error: {file_error}")
                return {}

            except (ValueError, TypeError) as data_error:
                print(f"❌ [STATE] Data validation error: {data_error}")
                return {}
        else:
            print(f"🐛 [STATE DEBUG] File {STATE_MAP_FILE} does not exist")

    except Exception as e:
        print(f"⚠️ [STATE] Unexpected error loading state_map: {e}")
        import traceback
        print(f"⚠️ [STATE] Traceback: {traceback.format_exc()}")

    print("🆕 [STATE] Creating new empty state_map")
    return {}

def save_state_map_sync(state_map):
    """Save state_map to disk with enhanced error handling (synchronous version)"""
    try:
        print(f"🐛 [STATE DEBUG] About to save state_map with {len(state_map)} entries")
        print(f"🐛 [STATE DEBUG] Keys to save: {list(state_map.keys())}")

        # Validate input data
        if not isinstance(state_map, dict):
            raise ValueError(f"Expected dict, got {type(state_map)}")

        # Convert integer keys to strings for JSON compatibility
        try:
            serializable_state = {str(k): v for k, v in state_map.items()}
        except (ValueError, TypeError) as conversion_error:
            print(f"❌ [STATE] Error converting keys to strings: {conversion_error}")
            return False

        # Create backup of existing file if it exists
        backup_created = False
        backup_file = f"{STATE_MAP_FILE}.backup"
        if os.path.exists(STATE_MAP_FILE):
            try:
                import shutil
                shutil.copy2(STATE_MAP_FILE, backup_file)
                backup_created = True
                print(f"📁 [STATE] Created backup: {backup_file}")
            except Exception as backup_error:
                print(f"⚠️ [STATE] Failed to create backup: {backup_error}")

        # Write to temporary file first for atomic operation
        temp_file = f"{STATE_MAP_FILE}.tmp"
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(serializable_state, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())  # Force OS to write to disk

            # Atomic move to final location
            import shutil
            shutil.move(temp_file, STATE_MAP_FILE)
            print(f"💾 [STATE] Saved {len(state_map)} entries to {STATE_MAP_FILE}")

        except (OSError, IOError) as file_error:
            print(f"❌ [STATE] File system error during save: {file_error}")
            # Clean up temp file if it exists
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
            return False

        # DIAGNOSTIC: Verify file was actually written
        try:
            if os.path.exists(STATE_MAP_FILE):
                file_size = os.path.getsize(STATE_MAP_FILE)
                if file_size == 0:
                    raise ValueError("File is empty after save")

                with open(STATE_MAP_FILE, 'r', encoding='utf-8') as f:
                    verification_data = json.load(f)
                    verification_keys = list(verification_data.keys())
                    print(f"🔍 [STATE VERIFY] File exists with {len(verification_data)} entries ({file_size} bytes)")
                    print(f"🔍 [STATE VERIFY] Keys in file: {verification_keys}")

                    # Verify data integrity
                    if len(verification_data) != len(state_map):
                        raise ValueError(f"Data count mismatch: expected {len(state_map)}, got {len(verification_data)}")
            else:
                raise FileNotFoundError("File does not exist after save")
        except Exception as verify_error:
            print(f"❌ [STATE VERIFY] Error verifying save: {verify_error}")
            # Try to restore from backup if verification fails
            if backup_created and os.path.exists(backup_file):
                try:
                    shutil.move(backup_file, STATE_MAP_FILE)
                    print(f"🔄 [STATE] Restored from backup due to verification failure")
                except Exception as restore_error:
                    print(f"❌ [STATE] Failed to restore from backup: {restore_error}")
            return False

        # Clean up backup file if everything succeeded
        if backup_created and os.path.exists(backup_file):
            try:
                os.remove(backup_file)
                print(f"🗑️ [STATE] Cleaned up backup file")
            except Exception as cleanup_error:
                print(f"⚠️ [STATE] Failed to clean up backup: {cleanup_error}")

        return True

    except (ValueError, TypeError) as data_error:
        print(f"❌ [STATE] Data validation error: {data_error}")
        return False
    except Exception as e:
        print(f"❌ [STATE] Unexpected error saving state_map: {e}")
        import traceback
        print(f"❌ [STATE] Traceback: {traceback.format_exc()}")
        return False

async def save_state_map(state_map):
    """Async wrapper for thread-safe state_map saving"""
    async with state_map_lock:
        return save_state_map_sync(state_map)

# Load persistent state_map
state_map = load_state_map()
print(f"🐛 [DEBUG] state_map initialized with {len(state_map)} entries")

# Thread-safe lock for state_map operations
state_map_lock = Lock()

async def get_state_map_entry(key):
    """Thread-safe getter for state_map entries"""
    async with state_map_lock:
        return state_map.get(key)

async def set_state_map_entry(key, value):
    """Thread-safe setter for state_map entries"""
    async with state_map_lock:
        state_map[key] = value

async def check_state_map_key(key):
    """Thread-safe check for key existence in state_map"""
    async with state_map_lock:
        return key in state_map

def create_timestamped_backup(state_map, operation_name="manual"):
    """Create a timestamped backup of the current state_map"""
    try:
        import datetime
        import shutil

        # Ensure backup directory exists
        os.makedirs(STATE_MAP_BACKUP_DIR, exist_ok=True)

        # Create timestamped filename
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"state_map_{operation_name}_{timestamp}.json"
        backup_path = os.path.join(STATE_MAP_BACKUP_DIR, backup_filename)

        # Convert to serializable format and save
        serializable_state = {str(k): v for k, v in state_map.items()}
        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(serializable_state, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        print(f"📁 [BACKUP] Created timestamped backup: {backup_filename}")

        # Clean up old backups
        cleanup_old_backups()

        return backup_path

    except Exception as e:
        print(f"❌ [BACKUP] Failed to create timestamped backup: {e}")
        return None

def cleanup_old_backups():
    """Clean up old backup files, keeping only the most recent ones"""
    try:
        if not os.path.exists(STATE_MAP_BACKUP_DIR):
            return

        # Get all backup files
        backup_files = []
        for filename in os.listdir(STATE_MAP_BACKUP_DIR):
            if filename.startswith("state_map_") and filename.endswith(".json"):
                filepath = os.path.join(STATE_MAP_BACKUP_DIR, filename)
                if os.path.isfile(filepath):
                    backup_files.append((os.path.getmtime(filepath), filepath))

        # Sort by modification time (newest first)
        backup_files.sort(reverse=True, key=lambda x: x[0])

        # Remove old backups
        if len(backup_files) > MAX_BACKUP_FILES:
            for _, filepath in backup_files[MAX_BACKUP_FILES:]:
                try:
                    os.remove(filepath)
                    print(f"🗑️ [BACKUP] Removed old backup: {os.path.basename(filepath)}")
                except Exception as e:
                    print(f"⚠️ [BACKUP] Failed to remove old backup {filepath}: {e}")

    except Exception as e:
        print(f"❌ [BACKUP] Error during backup cleanup: {e}")

async def backup_before_modification(operation_name="unknown"):
    """Create a backup before making modifications to state_map"""
    async with state_map_lock:
        return create_timestamped_backup(dict(state_map), operation_name)

def restore_from_backup(backup_path):
    """Restore state_map from a backup file"""
    try:
        if not os.path.exists(backup_path):
            print(f"❌ [RESTORE] Backup file not found: {backup_path}")
            return False

        print(f"🔄 [RESTORE] Restoring from backup: {os.path.basename(backup_path)}")

        with open(backup_path, 'r', encoding='utf-8') as f:
            loaded_state = json.load(f)

        # Convert back to integer keys
        restored_state = {}
        for k, v in loaded_state.items():
            try:
                int_key = int(k)
                restored_state[int_key] = v
            except (ValueError, TypeError) as key_error:
                print(f"⚠️ [RESTORE] Skipping invalid key '{k}': {key_error}")
                continue

        # Replace current state_map
        global state_map
        state_map = restored_state

        print(f"🔄 [RESTORE] Successfully restored {len(restored_state)} entries from backup")
        return True

    except Exception as e:
        print(f"❌ [RESTORE] Failed to restore from backup: {e}")
        return False

def list_available_backups():
    """List all available backup files"""
    try:
        if not os.path.exists(STATE_MAP_BACKUP_DIR):
            return []

        backups = []
        for filename in os.listdir(STATE_MAP_BACKUP_DIR):
            if filename.startswith("state_map_") and filename.endswith(".json"):
                filepath = os.path.join(STATE_MAP_BACKUP_DIR, filename)
                if os.path.isfile(filepath):
                    backups.append((os.path.getmtime(filepath), filename))

        # Sort by modification time (newest first)
        backups.sort(reverse=True, key=lambda x: x[0])

        return [filename for _, filename in backups]

    except Exception as e:
        print(f"❌ [BACKUP] Error listing backups: {e}")
        return []

message_queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
progress_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
account_ids = ['WhatsApp-1', 'WhatsApp-2']
user_data_dirs = ['./user_data/wa_profile_1', './user_data/wa_profile_2']

# Periodic saving configuration
PERIODIC_SAVE_INTERVAL = 86400  # Save every 5 minutes
periodic_save_task: asyncio.Task[None] | None = None

async def periodic_state_map_saver():
    """Background task that periodically saves state_map to prevent data loss"""
    global periodic_save_task

    print(f"💾 [PERIODIC SAVE] Starting periodic state_map saver (interval: {PERIODIC_SAVE_INTERVAL}s)")

    while True:
        try:
            await asyncio.sleep(PERIODIC_SAVE_INTERVAL)

            # Check if state_map has any entries before saving
            if len(state_map) > 0:
                print(f"💾 [PERIODIC SAVE] Saving state_map with {len(state_map)} entries...")
                save_success = save_state_map_sync(state_map)
                if save_success:
                    print(f"💾 [PERIODIC SAVE] Periodic save completed successfully")
                else:
                    print(f"⚠️ [PERIODIC SAVE] Periodic save failed")
            else:
                print(f"💾 [PERIODIC SAVE] Skipping save - state_map is empty")

        except asyncio.CancelledError:
            print(f"💾 [PERIODIC SAVE] Task cancelled, performing final save...")
            # Perform a final save before shutting down
            try:
                if len(state_map) > 0:
                    save_success = save_state_map_sync(state_map)
                    if save_success:
                        print(f"💾 [PERIODIC SAVE] Final save completed")
                    else:
                        print(f"⚠️ [PERIODIC SAVE] Final save failed")
            except Exception as final_save_error:
                print(f"❌ [PERIODIC SAVE] Error during final save: {final_save_error}")
            break

        except Exception as e:
            print(f"❌ [PERIODIC SAVE] Error in periodic save task: {e}")
            # Continue running despite errors to avoid stopping the periodic saves
            await asyncio.sleep(60)  # Wait a bit before retrying

async def start_periodic_saver():
    """Start the periodic state_map saving task"""
    global periodic_save_task

    if periodic_save_task is None or periodic_save_task.done():
        periodic_save_task = asyncio.create_task(periodic_state_map_saver())
        print(f"💾 [PERIODIC SAVE] Periodic saver task started")
        return periodic_save_task
    else:
        print(f"💾 [PERIODIC SAVE] Periodic saver task already running")
        return periodic_save_task

async def stop_periodic_saver():
    """Stop the periodic state_map saving task"""
    global periodic_save_task

    if periodic_save_task is not None and not periodic_save_task.done():
        print(f"💾 [PERIODIC SAVE] Stopping periodic saver task...")
        periodic_save_task.cancel()
        try:
            await periodic_save_task
            print(f"💾 [PERIODIC SAVE] Periodic saver task stopped successfully")
        except asyncio.CancelledError:
            print(f"💾 [PERIODIC SAVE] Periodic saver task was cancelled")
    else:
        print(f"💾 [PERIODIC SAVE] Periodic saver task was not running")

# Global flag for shutdown
shutdown_requested = False

def signal_handler(signum, frame):
    """Signal handler for graceful shutdown"""
    global shutdown_requested
    if not shutdown_requested:
        shutdown_requested = True
        print(f"\n🛑 [SIGNAL] Received signal {signum}, initiating graceful shutdown...")
        # Create a task to handle the shutdown asynchronously
        asyncio.create_task(graceful_shutdown(signum))

async def graceful_shutdown(signum):
    """Perform graceful shutdown with state saving"""
    try:
        print(f"🛑 [SHUTDOWN] Starting graceful shutdown sequence...")

        # Stop periodic saver first
        print(f"🛑 [SHUTDOWN] Stopping periodic saver...")
        await stop_periodic_saver()

        # Perform final state_map save
        print(f"🛑 [SHUTDOWN] Performing final state_map save...")
        if len(state_map) > 0:
            save_success = save_state_map_sync(state_map)
            if save_success:
                print(f"🛑 [SHUTDOWN] Final state_map save completed successfully")
            else:
                print(f"⚠️ [SHUTDOWN] Final state_map save failed")
        else:
            print(f"🛑 [SHUTDOWN] No state_map entries to save")

        print(f"🛑 [SHUTDOWN] Graceful shutdown completed for signal {signum}")

    except Exception as e:
        print(f"❌ [SHUTDOWN] Error during graceful shutdown: {e}")
    finally:
        # Force exit after cleanup
        print(f"🛑 [SHUTDOWN] Exiting application...")
        os._exit(0)

def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown"""
    try:
        # Handle SIGINT (Ctrl+C)
        signal.signal(signal.SIGINT, signal_handler)
        print(f"🛑 [SIGNALS] SIGINT handler registered")

        # Handle SIGTERM (termination signal)
        signal.signal(signal.SIGTERM, signal_handler)
        print(f"🛑 [SIGNALS] SIGTERM handler registered")

        # Handle SIGHUP (hangup) on Unix systems
        try:
            sighup_signal = getattr(signal, 'SIGHUP', None)
            if sighup_signal is not None:
                signal.signal(sighup_signal, signal_handler)
                print(f"🛑 [SIGNALS] SIGHUP handler registered")
        except (AttributeError, ValueError):
            pass  # SIGHUP not available on this platform

    except ValueError as e:
        print(f"⚠️ [SIGNALS] Could not setup signal handlers: {e}")
        print(f"⚠️ [SIGNALS] Signal handlers may not work properly on this platform")
    except Exception as e:
        print(f"❌ [SIGNALS] Unexpected error setting up signal handlers: {e}")

class AdaptiveDelay:
    """
    Intelligent adaptive delay system using Fibonacci sequence for progressive backoff.
    
    Features:
    - Starts with 3-second delays for responsiveness
    - Uses Fibonacci progression: 3, 5, 8, 13, 21, 34, 55, 89, 144, 233...
    - Caps at maximum 5 minutes (300 seconds)
    - Resets to minimum delay when messages are found
    - Tracks state per account for independent delay management
    """
    
    def __init__(self, base_delay=3, max_delay=300, active_delay=0.5):
        self.base_delay = base_delay  # Base delay in seconds (3s)
        self.max_delay = max_delay    # Maximum delay in seconds (300s = 5 minutes)
        self.active_delay = active_delay  # Delay when messages found (0.5s)
        
        # Track delay state per account: {account_id: {'consecutive_empty': int, 'current_delay': float}}
        self.account_states = {}
    
    def _get_fibonacci_delay(self, consecutive_empty_checks):
        """
        Calculate Fibonacci-based delay with base interval scaling.
        
        Fibonacci sequence: 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233...
        Scaled by base_delay: 3, 3, 6, 9, 15, 24, 39, 63, 102, 165, 267...
        Capped at max_delay: 3, 3, 6, 9, 15, 24, 39, 63, 102, 165, 267, 300, 300...
        """
        if consecutive_empty_checks <= 0:
            return self.base_delay
        
        # Generate Fibonacci number for the given position
        if consecutive_empty_checks == 1:
            fib = 1
        elif consecutive_empty_checks == 2:
            fib = 1
        else:
            # Calculate Fibonacci number iteratively
            a, b = 1, 1
            for _ in range(3, consecutive_empty_checks + 1):
                a, b = b, a + b
            fib = b
        
        # Scale by base delay and cap at maximum
        delay = min(fib * self.base_delay, self.max_delay)
        return delay
    
    def get_delay(self, account_id, found_messages=False):
        """
        Get the appropriate delay for an account based on message activity.
        
        Args:
            account_id (str): The account identifier
            found_messages (bool): True if messages were found in this check
            
        Returns:
            float: Delay in seconds to wait before next check
        """
        # Initialize account state if not exists
        if account_id not in self.account_states:
            self.account_states[account_id] = {
                'consecutive_empty': 0,
                'current_delay': self.base_delay
            }
        
        state = self.account_states[account_id]
        
        if found_messages:
            # Messages found - reset to active delay and clear empty counter
            state['consecutive_empty'] = 0
            state['current_delay'] = self.active_delay
            return self.active_delay
        else:
            # No messages found - increment counter and calculate new delay
            state['consecutive_empty'] += 1
            new_delay = self._get_fibonacci_delay(state['consecutive_empty'])
            state['current_delay'] = new_delay
            return new_delay
    
    def get_current_delay(self, account_id):
        """Get the current delay for an account without updating state."""
        if account_id not in self.account_states:
            return self.base_delay
        return self.account_states[account_id]['current_delay']
    
    def get_consecutive_empty_count(self, account_id):
        """Get the consecutive empty check count for an account."""
        if account_id not in self.account_states:
            return 0
        return self.account_states[account_id]['consecutive_empty']
    
    def reset_account(self, account_id):
        """Reset delay state for a specific account."""
        if account_id in self.account_states:
            self.account_states[account_id] = {
                'consecutive_empty': 0,
                'current_delay': self.base_delay
            }

# Initialize adaptive delay system
adaptive_delay = AdaptiveDelay(base_delay=3, max_delay=300, active_delay=0.5)

async def progressive_wait_for_search_results(page, account_id, search_term, max_attempts=5):
    """
    Progressive wait for search results with multiple timeout attempts.
    Returns (success, chat_count, error_message)
    """
    wait_times = [0.5, 1.0, 2.0, 3.0, 5.0]  # Progressive wait times

    for attempt in range(max_attempts):
        wait_time = wait_times[min(attempt, len(wait_times) - 1)]
        print(f"🔍 [{account_id}] SEARCH ATTEMPT {attempt + 1}: Waiting {wait_time}s for results...")

        await asyncio.sleep(wait_time)

        # Check for loading indicators first
        loading_selectors = [
            '[aria-label*="Cargando"]',
            '[aria-label*="Loading"]',
            'div[data-testid="loading"]',
            '.loading',
            '[role="progressbar"]'
        ]

        loading_found = False
        for loading_selector in loading_selectors:
            try:
                loading_element = await page.query_selector(loading_selector)
                if loading_element:
                    print(f"⏳ [{account_id}] Loading indicator found: {loading_selector}")
                    loading_found = True
                    # Wait for loading to disappear
                    await page.wait_for_selector(loading_selector, state='hidden', timeout=10000)
                    print(f"✅ [{account_id}] Loading indicator disappeared")
                    break
            except:
                continue

        # Alternative selectors for search results
        result_selectors = [
            "div[aria-label='Lista de chats'] div[role='listitem']",  # Primary Spanish
            "div[aria-label='Chat list'] div[role='listitem']",      # English
            "div[aria-label='Chats'] div[role='listitem']",         # Simple English
            "div[aria-label*='Lista'] div[role='listitem']",        # Contains "Lista"
            "[role='grid'] [role='listitem']",                      # Grid-based
            "div[data-testid='chat-list'] div[role='listitem']",    # Test ID
            "#pane-side div[role='listitem']",                      # Side pane
            "div[class*='chat-list'] div[role='listitem']",         # Class-based
        ]

        for selector_idx, chat_selector in enumerate(result_selectors):
            try:
                chat_elements = await page.query_selector_all(chat_selector)
                chat_count = len(chat_elements)

                if chat_count > 0:
                    print(f"✅ [{account_id}] SUCCESS: Found {chat_count} chats with selector {selector_idx + 1}: {chat_selector}")
                    return True, chat_count, None

                print(f"🔍 [{account_id}] Selector {selector_idx + 1} returned 0 results: {chat_selector}")

            except Exception as selector_error:
                print(f"⚠️ [{account_id}] Selector {selector_idx + 1} failed: {chat_selector} - {str(selector_error)}")
                continue

        print(f"❌ [{account_id}] ATTEMPT {attempt + 1} FAILED: No search results found after {wait_time}s")

    # All attempts failed
    return False, 0, f"No search results found for '{search_term}' after {max_attempts} attempts with progressive waits"

async def wait_for_chat_list_change(page, account_id, initial_count, timeout=10):
    """
    Wait for chat list to change count after search operation.
    Returns (changed, new_count)
    """
    try:
        print(f"📊 [{account_id}] MONITORING: Waiting for chat list change from {initial_count} items...")

        # Get initial chat count
        chat_selector = "div[aria-label='Lista de chats'] div[role='listitem']"
        initial_elements = await page.query_selector_all(chat_selector)
        initial_count = len(initial_elements)

        # Wait for count to change
        start_time = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            await asyncio.sleep(0.5)
            current_elements = await page.query_selector_all(chat_selector)
            current_count = len(current_elements)

            if current_count != initial_count:
                print(f"📊 [{account_id}] CHAT LIST CHANGED: {initial_count} → {current_count}")
                return True, current_count

        print(f"⏰ [{account_id}] TIMEOUT: Chat list count unchanged after {timeout}s")
        return False, initial_count

    except Exception as e:
        print(f"⚠️ [{account_id}] Error monitoring chat list change: {str(e)}")
        return False, initial_count

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
                    print(f"📝 [{account_id}] SENDING TEXT: Starting text message send process...")

                    # Send progress update - processing started
                    if response_msg.get('telegram_message_id'):
                        await send_progress_update(response_msg['telegram_message_id'], "processing",
                                                 f"Processing in {account_id}")
                    
                    try:
                        # Step 0: CRITICAL - Navigate back to chat list first
                        print(f"🏠 [{account_id}] NAVIGATION: Ensuring we're in chat list view...")
                        current_url = page.url
                        print(f"  📍 Current URL: {current_url}")
                        
                        # If we're in a specific chat, go back to main chat list
                        if "/chat/" in current_url or current_url.count('/') > 3:
                            print(f"  🔙 Currently in individual chat, navigating to main chat list...")
                            # Try multiple ways to get back to main chat list
                            try:
                                # Method 1: Try pressing Escape key
                                await page.keyboard.press('Escape')
                                await asyncio.sleep(1)
                                print(f"  ⌨️ Pressed Escape key")
                            except:
                                pass
                                
                            try:
                                # Method 2: Try to click WhatsApp logo/home
                                logo_element = await page.query_selector('img[alt="WhatsApp"]')
                                if logo_element:
                                    await logo_element.click()
                                    await asyncio.sleep(1)
                                    print(f"  🏠 Clicked WhatsApp logo")
                            except:
                                pass
                                
                            try:
                                # Method 3: Navigate to base WhatsApp URL
                                await page.goto('https://web.whatsapp.com/', wait_until='networkidle')
                                await asyncio.sleep(2)
                                print(f"  🌐 Navigated to base WhatsApp URL")
                            except:
                                pass
                        
                        # Verify we're in the main chat list
                        chat_list_element = await page.wait_for_selector("div[aria-label='Lista de chats']", timeout=10000)
                        if not chat_list_element:
                            raise Exception("Could not find chat list after navigation")
                        print(f"  ✅ Successfully in main chat list view")
                        
                        # Step 1: Enhanced search with diagnostic
                        print(f"🔍 [{account_id}] SEARCH STEP: Filling search box with '{response_msg['chat_target']}'")
                        search_element = await page.wait_for_selector(SEARCH_BOX, timeout=10000)
                        if not search_element:
                            raise Exception("Could not find search box")
                        
                        await search_element.click()
                        await search_element.fill(response_msg["chat_target"])
                        print(f"  ✅ Search box filled with: '{response_msg['chat_target']}'")
                        
                        # Step 2: Enhanced search with progressive wait and fallback mechanisms
                        print(f"👆 [{account_id}] CLICK STEP: Looking for chat result...")

                        # Get initial chat count for fallback mechanism
                        initial_chat_selector = "div[aria-label='Lista de chats'] div[role='listitem']"
                        initial_chats = await page.query_selector_all(initial_chat_selector)
                        initial_count = len(initial_chats)
                        print(f"  📊 Initial chat count: {initial_count}")

                        # Use progressive wait for search results
                        search_success, chat_count, search_error = await progressive_wait_for_search_results(
                            page, account_id, response_msg["chat_target"]
                        )

                        if not search_success:
                            # Fallback: Wait for chat list to change count
                            print(f"🔄 [{account_id}] FALLBACK: Monitoring chat list changes...")
                            list_changed, new_count = await wait_for_chat_list_change(page, account_id, initial_count, timeout=5)

                            if not list_changed:
                                # Final fallback: Try direct search result lookup
                                print(f"🔍 [{account_id}] FINAL FALLBACK: Direct search result lookup...")
                                chat_elements = await page.query_selector_all(CHAT_RESULT)
                                chat_count = len(chat_elements)
                                print(f"  📊 Found {chat_count} potential chats (fallback)")

                                if chat_count == 0:
                                    raise Exception(f"Search failed for '{response_msg['chat_target']}': {search_error}")
                            else:
                                chat_count = new_count
                                print(f"  📊 Using fallback chat count: {chat_count}")

                        # Look for target chat among results
                        target_found = False
                        target_name_clean = response_msg["chat_target"].replace('✨', '').replace('❤️', '').strip()

                        # Alternative selectors for finding chats
                        chat_selectors = [
                            "div[aria-label='Lista de chats'] div[role='listitem']",
                            "div[aria-label='Chat list'] div[role='listitem']",
                            "div[aria-label='Chats'] div[role='listitem']",
                            "[role='grid'] [role='listitem']",
                            "div[data-testid='chat-list'] div[role='listitem']",
                        ]

                        for selector_attempt, chat_selector in enumerate(chat_selectors):
                            # Send progress update - searching for recipient
                            if response_msg.get('telegram_message_id'):
                                await send_progress_update(response_msg['telegram_message_id'], "searching",
                                                         f"Searching for '{response_msg['chat_target']}' in {account_id}")
    
                            if target_found:
                                break

                            try:
                                chat_elements = await page.query_selector_all(chat_selector)
                                print(f"    🔍 [{account_id}] Trying selector {selector_attempt + 1}, found {len(chat_elements)} chats")

                                for i, chat_element in enumerate(chat_elements):
                                    try:
                                        chat_text = await chat_element.inner_text()
                                        chat_text_clean = chat_text.replace('✨', '').replace('❤️', '').strip()
                                        print(f"      📝 Chat {i+1} text: '{chat_text[:30]}...'")

                                        if target_name_clean.lower() in chat_text_clean.lower():
                                            print(f"      ✅ MATCH FOUND: Chat {i+1} matches target '{response_msg['chat_target']}'")
                                            await chat_element.click()
                                            target_found = True
                                            break
                                        else:
                                            print(f"      ❌ No match: '{target_name_clean}' not found in '{chat_text_clean[:30]}...'")
                                    except Exception as chat_error:
                                        print(f"      ⚠️ Error analyzing chat {i+1}: {chat_error}")
                                        continue

                            except Exception as selector_error:
                                print(f"    ⚠️ [{account_id}] Selector {selector_attempt + 1} failed: {str(selector_error)}")
                                continue

                        if not target_found:
                            # Enhanced diagnostic logging
                            print(f"❌ [{account_id}] DIAGNOSTIC: Search failed for '{response_msg['chat_target']}'")
                            print(f"  📊 Total chats found: {chat_count}")
                            print(f"  🔍 Searched for: '{target_name_clean}'")

                            # Try to get page content for debugging
                            try:
                                page_content = await page.content()
                                debug_file = f"./debug_search_failed_{account_id}.html"
                                with open(debug_file, 'w', encoding='utf-8') as f:
                                    f.write(page_content)
                                print(f"  📄 Debug HTML saved: {debug_file}")
                            except Exception as debug_error:
                                print(f"  ⚠️ Could not save debug HTML: {str(debug_error)}")

                            raise Exception(f"Could not find chat '{response_msg['chat_target']}' in {chat_count} search results")
                        
                        # Step 3: Wait for navigation
                        print(f"⏳ [{account_id}] NAVIGATION: Waiting for chat to load...")
                        await asyncio.sleep(2)  # Wait for chat to load
                        
                        # Step 4: Enhanced message input
                        print(f"✏️ [{account_id}] MESSAGE STEP: Typing message '{response_msg['text'][:50]}...'")
                        message_element = await page.wait_for_selector(MESSAGE_INPUT, timeout=10000)
                        if not message_element:
                            raise Exception("Could not find message input")
                            
                        await message_element.click()
                        await message_element.fill(response_msg["text"])
                        print(f"  ✅ Message typed successfully")
                        
                        # Step 5: Enhanced send
                        print(f"🚀 [{account_id}] SEND STEP: Clicking send button...")
                        send_element = await page.wait_for_selector(SEND_BUTTON, timeout=5000)
                        if not send_element:
                            raise Exception("Could not find send button")
                            
                        await send_element.click()
                        print(f"  ✅ Send button clicked successfully")
                        
                        print(f"✅ [{account_id}] TEXT MESSAGE SENT: Process completed for '{response_msg['chat_target']}'")

                        # Send success confirmation
                        print(f"🐛 [DEBUG] 📤 STATUS MSG: response_msg fields: {list(response_msg.keys())}")
                        print(f"🐛 [DEBUG] 📤 STATUS MSG: telegram_message_id value: {response_msg.get('telegram_message_id')}")
                        # Send progress update - message sent successfully
                        if response_msg.get('telegram_message_id'):
                            await send_progress_update(response_msg['telegram_message_id'], "sent",
                                                     f"Sent to {response_msg['chat_target']} via {account_id}")

                        await message_queue.put(('status', {
                            "text": f"✅ Message sent successfully!\n📱 Account: {account_id}\n👤 Target: {response_msg['chat_target']}\n📝 Type: Text",
                        }))

                        # Send final progress update - message completed
                        if response_msg.get('telegram_message_id'):
                            await send_progress_update(response_msg['telegram_message_id'], "completed",
                                                     f"Message delivered successfully via {account_id}")
                        print(f"📤 [{account_id}] CONFIRMATION: Success status sent to queue")

                    except Exception as send_error:
                        print(f"❌ [{account_id}] SEND ERROR: {send_error}")

                        # Send failure confirmation
                        print(f"🐛 [DEBUG] ❌ TEXT FAILURE: response_msg fields: {list(response_msg.keys())}")
                        print(f"🐛 [DEBUG] ❌ TEXT FAILURE: telegram_message_id value: {response_msg.get('telegram_message_id')}")
                        # Send progress update - message failed
                        if response_msg.get('telegram_message_id'):
                            await send_progress_update(response_msg['telegram_message_id'], "error",
                                                     f"Failed to send to {response_msg['chat_target']}: {str(send_error)}")

                        await message_queue.put(('status', {
                            "text": f"❌ Message failed to send!\n📱 Account: {account_id}\n👤 Target: {response_msg['chat_target']}\n📝 Type: Text\n⚠️ Error: {str(send_error)}",
                            "original_message_id": response_msg.get("telegram_message_id"),
                            "status_type": "failure",
                            "account_id": account_id,
                            "chat_target": response_msg['chat_target'],
                            "error": str(send_error)
                        }))
                        print(f"📤 [{account_id}] CONFIRMATION: Failure status sent to queue")
                        raise send_error
                elif response_msg["type"] == "media":
                    print(f"📎 [{account_id}] SENDING MEDIA: Starting media message send process...")
                    
                    try:
                        # Step 0: CRITICAL - Navigate back to chat list first (same as text)
                        print(f"🏠 [{account_id}] NAVIGATION: Ensuring we're in chat list view...")
                        current_url = page.url
                        print(f"  📍 Current URL: {current_url}")
                        
                        # If we're in a specific chat, go back to main chat list
                        if "/chat/" in current_url or current_url.count('/') > 3:
                            print(f"  🔙 Currently in individual chat, navigating to main chat list...")
                            # Try multiple ways to get back to main chat list
                            try:
                                await page.keyboard.press('Escape')
                                await asyncio.sleep(1)
                                print(f"  ⌨️ Pressed Escape key")
                            except:
                                pass
                                
                            try:
                                logo_element = await page.query_selector('img[alt="WhatsApp"]')
                                if logo_element:
                                    await logo_element.click()
                                    await asyncio.sleep(1)
                                    print(f"  🏠 Clicked WhatsApp logo")
                            except:
                                pass
                                
                            try:
                                await page.goto('https://web.whatsapp.com/', wait_until='networkidle')
                                await asyncio.sleep(2)
                                print(f"  🌐 Navigated to base WhatsApp URL")
                            except:
                                pass
                        
                        # Verify we're in the main chat list
                        chat_list_element = await page.wait_for_selector("div[aria-label='Lista de chats']", timeout=10000)
                        if not chat_list_element:
                            raise Exception("Could not find chat list after navigation")
                        print(f"  ✅ Successfully in main chat list view")
                        
                        # Step 1: Enhanced search with diagnostic
                        print(f"🔍 [{account_id}] SEARCH STEP: Filling search box with '{response_msg['chat_target']}'")
                        search_element = await page.wait_for_selector(SEARCH_BOX, timeout=10000)
                        if not search_element:
                            raise Exception("Could not find search box")
                        
                        await search_element.click()
                        await search_element.fill(response_msg["chat_target"])
                        print(f"  ✅ Search box filled with: '{response_msg['chat_target']}'")
                        
                        # Step 2: Wait for search results and click chat
                        print(f"👆 [{account_id}] CLICK STEP: Looking for chat result...")
                        await asyncio.sleep(2)  # Increased wait time for search results
                        
                        chat_elements = await page.query_selector_all(CHAT_RESULT)
                        print(f"  📊 Found {len(chat_elements)} potential chats")
                        
                        target_found = False
                        target_name_clean = response_msg["chat_target"].replace('✨', '').replace('❤️', '').strip()
                        
                        for i, chat_element in enumerate(chat_elements):
                            try:
                                chat_text = await chat_element.inner_text()
                                chat_text_clean = chat_text.replace('✨', '').replace('❤️', '').strip()
                                print(f"    📝 Chat {i+1} text: '{chat_text[:30]}...'")
                                
                                if target_name_clean.lower() in chat_text_clean.lower():
                                    print(f"  ✅ MATCH FOUND: Chat {i+1} matches target '{response_msg['chat_target']}'")
                                    await chat_element.click()
                                    target_found = True
                                    break
                            except Exception as chat_error:
                                print(f"    ⚠️ Error analyzing chat {i+1}: {chat_error}")
                                continue
                        
                        if not target_found:
                            raise Exception(f"Could not find chat '{response_msg['chat_target']}' in {len(chat_elements)} search results")
                        
                        # Step 3: Wait for navigation
                        print(f"⏳ [{account_id}] NAVIGATION: Waiting for chat to load...")
                        await asyncio.sleep(2)  # Wait for chat to load
                        
                        # Step 4: Enhanced media attachment
                        print(f"📎 [{account_id}] ATTACH STEP: Attaching media file...")
                        async with page.expect_file_chooser() as fc_info:
                            attach_element = await page.wait_for_selector(ATTACH_BUTTON, timeout=10000)
                            if not attach_element:
                                raise Exception("Could not find attach button")
                            await attach_element.click()
                            print(f"  ✅ Attach button clicked")
                            
                            # Select appropriate button
                            media_button = DOCUMENT_BUTTON if response_msg["file_type"] == "document" else PHOTO_BUTTON
                            media_element = await page.wait_for_selector(media_button, timeout=5000)
                            if not media_element:
                                raise Exception(f"Could not find {response_msg['file_type']} button")
                            await media_element.click()
                            print(f"  ✅ {response_msg['file_type']} button clicked")
                            
                        file_chooser = await fc_info.value
                        await file_chooser.set_files(response_msg["file_path"])
                        print(f"  ✅ File selected: {response_msg['file_path']}")
                        
                        await asyncio.sleep(0.5)
                        
                        # Step 5: Enhanced send
                        print(f"🚀 [{account_id}] SEND STEP: Clicking send button...")
                        send_element = await page.wait_for_selector(SEND_BUTTON, timeout=5000)
                        if not send_element:
                            raise Exception("Could not find send button")
                            
                        await send_element.click()
                        print(f"  ✅ Send button clicked successfully")
                        
                        # Clean up file
                        try:
                            os.remove(response_msg["file_path"])
                            print(f"  🗑️ Temporary file removed: {response_msg['file_path']}")
                        except Exception as cleanup_error:
                            print(f"  ⚠️ Could not remove file: {cleanup_error}")
                        
                        print(f"✅ [{account_id}] MEDIA MESSAGE SENT: Process completed for '{response_msg['chat_target']}'")

                        # Send success confirmation for media
                        print(f"🐛 [DEBUG] 📤 MEDIA STATUS MSG: response_msg fields: {list(response_msg.keys())}")
                        print(f"🐛 [DEBUG] 📤 MEDIA STATUS MSG: telegram_message_id value: {response_msg.get('telegram_message_id')}")
                        await message_queue.put(('status', {
                            "text": f"✅ Media sent successfully!\n📱 Account: {account_id}\n👤 Target: {response_msg['chat_target']}\n📎 Type: Media",
                            "original_message_id": response_msg.get("telegram_message_id"),
                            "status_type": "success",
                            "account_id": account_id,
                            "chat_target": response_msg['chat_target']
                        }))
                        print(f"📤 [{account_id}] CONFIRMATION: Media success status sent to queue")

                    except Exception as send_error:
                        print(f"❌ [{account_id}] MEDIA SEND ERROR: {send_error}")

                        # Send failure confirmation for media
                        print(f"🐛 [DEBUG] ❌ MEDIA FAILURE: response_msg fields: {list(response_msg.keys())}")
                        print(f"🐛 [DEBUG] ❌ MEDIA FAILURE: telegram_message_id value: {response_msg.get('telegram_message_id')}")
                        await message_queue.put(('status', {
                            "text": f"❌ Media failed to send!\n📱 Account: {account_id}\n👤 Target: {response_msg['chat_target']}\n📎 Type: Media\n⚠️ Error: {str(send_error)}",
                            "original_message_id": response_msg.get("telegram_message_id"),
                            "status_type": "failure",
                            "account_id": account_id,
                            "chat_target": response_msg['chat_target'],
                            "error": str(send_error)
                        }))
                        print(f"📤 [{account_id}] CONFIRMATION: Media failure status sent to queue")

                        raise send_error
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
                
                # ADAPTIVE DELAY SYSTEM: Use Fibonacci-based progressive backoff
                found_unread = len(found_unread_chats) > 0
                delay_seconds = adaptive_delay.get_delay(account_id, found_unread)
                consecutive_empty = adaptive_delay.get_consecutive_empty_count(account_id)
                
                if found_unread:
                    print(f"[{account_id}] Processing {len(found_unread_chats)} chats with unread messages...")
                    print(f"[{account_id}] 🚀 ADAPTIVE DELAY: Using active delay of {delay_seconds}s (messages found, reset to responsive mode)")
                else:
                    print(f"[{account_id}] No unread messages found (consecutive empty checks: {consecutive_empty})")
                    if consecutive_empty == 1:
                        print(f"[{account_id}] ⏳ ADAPTIVE DELAY: First empty check - using {delay_seconds}s delay")
                    elif delay_seconds >= 300:
                        print(f"[{account_id}] ⏳ ADAPTIVE DELAY: Maximum backoff reached - using {delay_seconds}s delay (5 minutes)")
                    else:
                        print(f"[{account_id}] ⏳ ADAPTIVE DELAY: Progressive backoff - using {delay_seconds}s delay (Fibonacci sequence)")
                
                await asyncio.sleep(delay_seconds)
                
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
                                
                                # DIAGNOSTIC: Check for multimedia content before processing as text
                                print(f"[{account_id}] 🔍 MULTIMEDIA CHECK: Looking for images/media in message {msg_index + 1}...")
                                
                                # Check for images - PRIORITIZE FULL RESOLUTION over thumbnails
                                image_selectors = [
                                    'div[aria-label="Abrir foto"]',              # Spanish: Open photo (FULL RESOLUTION)
                                    'div[aria-label="Open photo"]',              # English: Open photo (FULL RESOLUTION)
                                    'div[role="button"][aria-label*="foto"]',    # Photo button (Spanish) (FULL RESOLUTION)
                                    'div[role="button"][aria-label*="photo"]',   # Photo button (English) (FULL RESOLUTION)
                                    'img[src*="blob:"]',                         # Blob URLs (thumbnails - fallback only)
                                    'img[src^="data:image"]',                    # Data URIs (thumbnails - fallback only)
                                ]
                                
                                has_image = False
                                image_src = None
                                
                                for img_selector in image_selectors:
                                    try:
                                        img_element = await msg.query_selector(img_selector)
                                        if img_element:
                                            print(f"[{account_id}] 🖼️ FOUND IMAGE with selector: {img_selector}")
                                            # Try to get image source
                                            if 'img' in img_selector:
                                                image_src = await img_element.get_attribute('src')
                                            else:
                                                # Look for img inside the div
                                                inner_img = await img_element.query_selector('img')
                                                if inner_img:
                                                    image_src = await inner_img.get_attribute('src')
                                            
                                            if image_src:
                                                print(f"[{account_id}] 📸 Image source: {image_src[:100]}...")
                                                has_image = True
                                                break
                                    except Exception as img_error:
                                        print(f"[{account_id}] ⚠️ Image selector {img_selector} failed: {img_error}")
                                        continue
                                
                                if has_image and image_src:
                                    print(f"[{account_id}] 🎯 PROCESSING AS IMAGE MESSAGE")
                                    message_data = {
                                        "type": "media",
                                        "file_type": "photo",
                                        "file_src": image_src,
                                        "caption": f'[{account_id}] 📸 Imagen de {sender_name}',
                                        "account_id": account_id,
                                        "sender": sender_name
                                    }
                                    print(f"[{account_id}] 📤 [QUEUE] Adding image message to queue: {message_data}")
                                    await message_queue.put(('whatsapp', message_data))
                                    print(f"[{account_id}] 📤 [QUEUE] ✅ Image message added to queue successfully")
                                
                                elif msg_text and msg_text.strip():
                                    print(f"[{account_id}] 📝 PROCESSING AS TEXT MESSAGE")
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
                                    print(f"[{account_id}] ❌ FAILED to extract text or media from message {msg_index + 1}")
                                    # DIAGNOSTIC: Log message element structure
                                    try:
                                        outer_html = await msg.evaluate('el => el.outerHTML')
                                        print(f"[{account_id}] 🔬 Message {msg_index + 1} HTML structure: {outer_html[:500]}...")
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
        await message.reply("Bienvenido al puente WhatsApp-Telegram. Responde a un mensaje para enviar una respuesta a WhatsApp en el chat correspondiente.")
    
    @dp.message()
    async def handle_text(message: types.Message):
        print(f"🐛 [DEBUG] handle_text called - message_id: {message.message_id}")
        print(f"🐛 [DEBUG] Reply to message: {message.reply_to_message is not None}")

        # Send initial progress message
        await send_progress_message(bot, TELEGRAM_CHAT_ID, message.message_id, "received")
        
        if message.reply_to_message:
            reply_to_id = message.reply_to_message.message_id
            print(f"🐛 [DEBUG] Looking up state_map for reply_to_message_id: {reply_to_id}")
            print(f"🐛 [DEBUG] Current state_map size: {len(state_map)} entries")
            print(f"🐛 [DEBUG] Current state_map keys: {list(state_map.keys())}")
            key_exists = await check_state_map_key(reply_to_id)
            print(f"🐛 [DEBUG] Key exists in state_map: {key_exists}")

            if key_exists:
                state = await get_state_map_entry(reply_to_id)
                if state is None:
                    print(f"⚠️ [TELEGRAM] State lookup returned None for reply_to_id: {reply_to_id}")
                    await message.reply("❌ Error: No se pudo encontrar la información del chat original")
                    return
                print(f"🐛 [DEBUG] ✅ STATE_MAP LOOKUP SUCCESS - Found: {state}")
                print(f"🐛 [DEBUG] 📝 Creating response_msg - message.message_id: {message.message_id}")
                response_msg = {
                    "chat_target": state["chat_original"],
                    "text": message.text,
                    "type": "text",
                    "account": state["account"],
                    "telegram_message_id": message.message_id
                }
                print(f"🐛 [DEBUG] 📝 response_msg fields: {list(response_msg.keys())}")
                print(f"🐛 [DEBUG] Sending response to queue: {response_msg}")
                await response_queues[state["account"]].put(response_msg)
                
                # Success feedback
                await message.reply(f"✅ Respuesta enviada a {state['chat_original']} vía {state['account']}")
            else:
                print(f"🐛 [DEBUG] ❌ STATE_MAP LOOKUP FAILED - Key {reply_to_id} not found")
                
                # Detailed error message
                if len(state_map) == 0:
                    error_msg = (
                        "❌ No se puede enviar la respuesta.\n\n"
                        "🔄 **Causa**: El bot se reinició y perdió la información de mensajes anteriores.\n\n"
                        "💡 **Solución**: \n"
                        "• Espera a que llegue un nuevo mensaje de WhatsApp\n"
                        "• Luego responde a ese mensaje nuevo"
                    )
                else:
                    available_ids = list(state_map.keys())
                    error_msg = (
                        f"❌ No se puede enviar la respuesta.\n\n"
                        f"🔍 **Mensaje ID {reply_to_id}** no encontrado en el sistema.\n\n"
                        f"📋 **IDs disponibles**: {available_ids}\n\n"
                        f"💡 **Solución**: Responde solo a mensajes recientes de WhatsApp"
                    )
                
                await message.reply(error_msg, parse_mode="Markdown")
        else:
            print(f"🐛 [DEBUG] ❌ No reply_to_message found")
            
            error_msg = (
                "❌ Comando no válido.\n\n"
                "📝 **Para enviar un mensaje a WhatsApp**:\n"
                "1️⃣ Espera que llegue un mensaje de WhatsApp\n"
                "2️⃣ Haz clic en 'Responder' a ese mensaje\n"
                "3️⃣ Escribe tu respuesta\n\n"
                "ℹ️ No puedes enviar mensajes directos, solo responder."
            )
            
            await message.reply(error_msg, parse_mode="Markdown")
    
    @dp.message((F.photo) | (F.document))
    async def handle_media(message: types.Message):
        print(f"🐛 [DEBUG] handle_media called - message_id: {message.message_id}")
        print(f"🐛 [DEBUG] Reply to message: {message.reply_to_message is not None}")
        
        if message.reply_to_message:
            reply_to_id = message.reply_to_message.message_id
            print(f"🐛 [DEBUG] Looking up state_map for reply_to_message_id (media): {reply_to_id}")
            print(f"🐛 [DEBUG] Current state_map size: {len(state_map)} entries")
            key_exists = await check_state_map_key(reply_to_id)
            print(f"🐛 [DEBUG] Key exists in state_map: {key_exists}")

            if key_exists:
                state = await get_state_map_entry(reply_to_id)
                if state is None:
                    print(f"⚠️ [TELEGRAM] State lookup returned None for reply_to_id: {reply_to_id}")
                    await message.reply("❌ Error: No se pudo encontrar la información del chat original")
                    return
                print(f"🐛 [DEBUG] ✅ STATE_MAP LOOKUP SUCCESS (media) - Found: {state}")
                
                if message.photo:
                    file_id = message.photo[-1].file_id
                    file_type = "photo"
                    media_type = "📸 Foto"
                elif message.document:
                    file_id = message.document.file_id
                    file_type = "document"
                    media_type = "📁 Documento"
                else:
                    await message.reply("❌ Tipo de archivo no soportado.")
                    return
                
                try:
                    file = await bot.get_file(file_id)
                    if not file.file_path:
                        await message.reply("❌ Error: No se pudo obtener el archivo.")
                        return

                    file_name = file.file_path.split('/')[-1]
                    file_path = f"./downloads/{file_name}"
                    await bot.download_file(file.file_path, destination=file_path)
                    
                    print(f"🐛 [DEBUG] Sending media response to queue: account={state['account']}, chat_target={state['chat_original']}")
                    print(f"🐛 [DEBUG] 📎 Creating media response_msg - message.message_id: {message.message_id}")
                    media_response_msg = {
                        "type": "media",
                        "file_path": file_path,
                        "file_type": file_type,
                        "chat_target": state["chat_original"],
                        "account": state["account"],
                        "telegram_message_id": message.message_id
                    }
                    print(f"🐛 [DEBUG] 📎 media_response_msg fields: {list(media_response_msg.keys())}")
                    await response_queues[state["account"]].put(media_response_msg)
                    
                    # Success feedback
                    await message.reply(f"✅ {media_type} enviado a {state['chat_original']} vía {state['account']}")
                    
                except Exception as e:
                    await message.reply(f"❌ Error procesando archivo: {str(e)}")
            else:
                print(f"🐛 [DEBUG] ❌ STATE_MAP LOOKUP FAILED (media) - Key {reply_to_id} not found")
                
                # Same detailed error as text handler
                if len(state_map) == 0:
                    error_msg = (
                        "❌ No se puede enviar el archivo.\n\n"
                        "🔄 **Causa**: El bot se reinició y perdió la información de mensajes anteriores.\n\n"
                        "💡 **Solución**: \n"
                        "• Espera a que llegue un nuevo mensaje de WhatsApp\n"
                        "• Luego responde con tu archivo a ese mensaje nuevo"
                    )
                else:
                    available_ids = list(state_map.keys())
                    error_msg = (
                        f"❌ No se puede enviar el archivo.\n\n"
                        f"🔍 **Mensaje ID {reply_to_id}** no encontrado en el sistema.\n\n"
                        f"📋 **IDs disponibles**: {available_ids}\n\n"
                        f"💡 **Solución**: Responde solo a mensajes recientes de WhatsApp"
                    )
                
                await message.reply(error_msg, parse_mode="Markdown")
        else:
            print(f"🐛 [DEBUG] ❌ No reply_to_message found (media)")
            
            error_msg = (
                "❌ Comando no válido para archivos.\n\n"
                "📎 **Para enviar archivos a WhatsApp**:\n"
                "1️⃣ Espera que llegue un mensaje de WhatsApp\n"
                "2️⃣ Haz clic en 'Responder' a ese mensaje\n"
                "3️⃣ Adjunta tu foto/documento como respuesta\n\n"
                "ℹ️ No puedes enviar archivos directos, solo como respuesta."
            )
            
            await message.reply(error_msg, parse_mode="Markdown")
    
    async def queue_consumer():
        print("🚀 [QUEUE CONSUMER] Starting queue consumer...")
        while True:
            try:
                print("🔄 [QUEUE CONSUMER] Waiting for messages in queue...")

                # Handle progress updates first (non-blocking)
                try:
                    progress_update = progress_queue.get_nowait()
                    telegram_message_id = progress_update.get('telegram_message_id')
                    state = progress_update.get('state')
                    details = progress_update.get('details', '')

                    if telegram_message_id and state:
                        try:
                            await update_progress_message(bot, TELEGRAM_CHAT_ID, telegram_message_id, state, details)
                        except Exception as progress_error:
                            print(f"⚠️ [PROGRESS] Error processing progress update for {telegram_message_id}: {progress_error}")
                except asyncio.QueueEmpty:
                    pass  # No progress updates available

                source, content = await message_queue.get()
                print(f"📨 [QUEUE CONSUMER] Received message from {source}: {content}")
                
                if source == 'status':
                    print(f"📤 [TELEGRAM] Processing status message: {content}")
                    try:
                        # Send the detailed status message to Telegram
                        sent_msg = await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=content["text"])
                        print(f"📤 [TELEGRAM] Status message sent successfully, received message_id: {sent_msg.message_id}")

                        # If this is a reply (has original_message_id), we could add reply logic here
                        # For now, just send the status as a regular message

                    except Exception as status_error:
                        print(f"❌ [TELEGRAM] Error sending status message: {status_error}")

                elif source == 'whatsapp':
                    if content["type"] == "text":
                        print(f"📤 [TELEGRAM] Sending text message to Telegram...")
                        print(f"🐛 [DEBUG] About to send message with content: account_id='{content["account_id"]}', sender='{content["sender"]}'")
                        try:
                            sent_msg = await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=content["text"])
                            print(f"🐛 [DEBUG] Message sent successfully, received message_id: {sent_msg.message_id}")
                            
                            # Save to state_map
                            state_entry = {
                                'account': content["account_id"],
                                'chat_original': content["sender"]
                            }
                            state_map[sent_msg.message_id] = state_entry
                            save_success = await save_state_map(state_map)  # Persist to disk after state_map update
                            if not save_success:
                                print(f"⚠️ [STATE] Failed to persist state_map after text message")

                            print(f"🐛 [DEBUG] ✅ STATE_MAP SAVED - Key: {sent_msg.message_id}, Value: {state_entry}")
                            print(f"🐛 [DEBUG] Current state_map size: {len(state_map)} entries")
                            print(f"🐛 [DEBUG] Current state_map keys: {list(state_map.keys())}")
                            print(f"✅ [TELEGRAM] Text message sent successfully! Message ID: {sent_msg.message_id}")
                        except Exception as telegram_error:
                            print(f"❌ [TELEGRAM] Failed to send text message: {telegram_error}")
                            print(f"🐛 [DEBUG] ❌ STATE_MAP NOT SAVED due to send failure")
                            
                    elif content["type"] == "media":
                        print(f"📤 [TELEGRAM] Sending media message to Telegram...")
                        print(f"🐛 [DEBUG] About to send media with content: account_id='{content["account_id"]}', sender='{content["sender"]}'")
                        try:
                            # Handle WhatsApp blob URLs and data URIs (from new image detection)
                            if "file_src" in content:
                                file_src = content['file_src']
                                print(f"📥 [TELEGRAM] Processing WhatsApp image from: {file_src[:100]}...")
                                
                                # Handle data URI images (can be sent directly)
                                if file_src.startswith('data:image/'):
                                    print(f"🖼️ [TELEGRAM] Processing data URI image...")
                                    try:
                                        import base64
                                        import io
                                        
                                        # Extract base64 data from data URI
                                        header, data = file_src.split(',', 1)
                                        image_data = base64.b64decode(data)
                                        
                                        # Create file-like object
                                        image_file = io.BytesIO(image_data)
                                        image_file.name = "whatsapp_image.jpg"
                                        
                                        # Send actual image to Telegram
                                        caption_text = content.get("caption", f"[{content['account_id']}] 📸 Imagen de {content['sender']}")
                                        sent_msg = await bot.send_photo(
                                            chat_id=TELEGRAM_CHAT_ID,
                                            photo=types.BufferedInputFile(image_data, filename="whatsapp_image.jpg"),
                                            caption=caption_text
                                        )
                                        print(f"📸 [TELEGRAM] Successfully sent data URI image!")
                                        
                                    except Exception as data_uri_error:
                                        print(f"❌ [TELEGRAM] Failed to process data URI: {data_uri_error}")
                                        # Fallback to text notification
                                        caption_text = content.get("caption", f"[{content['account_id']}] 📸 Imagen de {content['sender']}")
                                        sent_msg = await bot.send_message(
                                            chat_id=TELEGRAM_CHAT_ID,
                                            text=f"{caption_text}\n\n⚠️ Error procesando imagen data URI"
                                        )
                                
                                # Handle blob URLs (send notification for now)
                                elif file_src.startswith('blob:'):
                                    print(f"🔗 [TELEGRAM] Blob URL detected - sending notification...")
                                    caption_text = content.get("caption", f"[{content['account_id']}] 📸 Imagen de {content['sender']}")
                                    sent_msg = await bot.send_message(
                                        chat_id=TELEGRAM_CHAT_ID,
                                        text=f"{caption_text}\n\n🔗 Imagen desde WhatsApp Web (URL blob no descargable directamente)"
                                    )
                                    print(f"📝 [TELEGRAM] Sent blob URL notification")
                                
                                else:
                                    print(f"❌ [TELEGRAM] Unknown image source format: {file_src[:50]}...")
                                    caption_text = content.get("caption", f"[{content['account_id']}] 📸 Imagen de {content['sender']}")
                                    sent_msg = await bot.send_message(
                                        chat_id=TELEGRAM_CHAT_ID,
                                        text=f"{caption_text}\n\n❓ Formato de imagen desconocido"
                                    )
                                
                            # Handle traditional file paths (from Telegram to WhatsApp media)
                            elif "file_path" in content:
                                file = types.FSInputFile(content["file_path"])
                                sent_msg = None
                                if content["file_type"] == "photo":
                                    sent_msg = await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=file)
                                elif content["file_type"] == "document":
                                    sent_msg = await bot.send_document(chat_id=TELEGRAM_CHAT_ID, document=file)
                                
                                # Clean up temporary file
                                try:
                                    os.remove(content["file_path"])
                                    print(f"🗑️ [CLEANUP] Removed temporary file: {content['file_path']}")
                                except Exception as cleanup_error:
                                    print(f"⚠️ [CLEANUP] Could not remove file: {cleanup_error}")
                            else:
                                print(f"❌ [TELEGRAM] Media content missing both file_src and file_path")
                                continue
                            
                            if sent_msg:
                                print(f"🐛 [DEBUG] Media sent successfully, received message_id: {sent_msg.message_id}")
                                
                                # Save to state_map
                                state_entry = {
                                    'account': content["account_id"],
                                    'chat_original': content["sender"]
                                }
                                state_map[sent_msg.message_id] = state_entry
                                save_success = await save_state_map(state_map)  # Persist to disk
                                if not save_success:
                                    print(f"⚠️ [STATE] Failed to persist state_map after media message")

                                print(f"🐛 [DEBUG] ✅ STATE_MAP SAVED - Key: {sent_msg.message_id}, Value: {state_entry}")
                                print(f"🐛 [DEBUG] Current state_map size: {len(state_map)} entries")
                                print(f"🐛 [DEBUG] Current state_map keys: {list(state_map.keys())}")
                                print(f"✅ [TELEGRAM] Media message sent successfully! Message ID: {sent_msg.message_id}")
                            else:
                                print(f"🐛 [DEBUG] ❌ sent_msg is None, STATE_MAP NOT SAVED")
                                
                        except Exception as telegram_error:
                            print(f"❌ [TELEGRAM] Failed to send media message: {telegram_error}")
                            print(f"🐛 [DEBUG] ❌ STATE_MAP NOT SAVED due to media send failure")
                            
                    elif content["type"] == "status":
                        print(f"📤 [TELEGRAM] Sending status message to Telegram...")
                        try:
                            # Check if this is a reply to an original message
                            reply_to_message_id = content.get("original_message_id")
                            if reply_to_message_id:
                                # Send as reply to original message
                                await bot.send_message(
                                    chat_id=TELEGRAM_CHAT_ID,
                                    text=content["text"],
                                    reply_to_message_id=reply_to_message_id
                                )
                                print(f"✅ [TELEGRAM] Status reply sent successfully to message {reply_to_message_id}!")
                            else:
                                # Send as regular message
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

    # Start periodic state_map saving
    periodic_task = await start_periodic_saver()

    # Setup signal handlers for graceful shutdown
    setup_signal_handlers()

    print(f"🚀 [MAIN] TELEGRAM_TOKEN configured: {'Yes' if TELEGRAM_TOKEN else 'No'}")
    print(f"🚀 [MAIN] TELEGRAM_CHAT_ID: {TELEGRAM_CHAT_ID}")
    
    response_queues: dict[str, asyncio.Queue[dict[str, Any]]] = {
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
    finally:
        # Stop periodic saver on shutdown
        print("🚀 [MAIN] Shutting down periodic saver...")
        await stop_periodic_saver()
        print("🚀 [MAIN] Periodic saver stopped")

if __name__ == "__main__":
    asyncio.run(main())