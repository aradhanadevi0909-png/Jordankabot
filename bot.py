import asyncio
import logging
import os
import re
from typing import Dict, Set
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
import aiohttp
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot configuration
API_TOKEN = "7730082684:AAHIS5YbOH0O89bUsb5mRmf6O6TcSnP_1TE"  # Replace with your bot token
OWNER_ID = 5690180919  # Replace with your Telegram user ID

# API for checking CC (example - replace with actual API)
CC_CHECK_API = "https://bot-production-2e0c.up.railway.app/check"  # Replace with actual API

# Initialize bot and dispatcher
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Store approved users and active check processes
approved_users: Set[int] = set()
active_checks: Dict[int, asyncio.Task] = {}
stop_flags: Dict[int, bool] = {}

# States for FSM
class CheckStates(StatesGroup):
    waiting_for_stop = State()

# CC Checking function
async def check_cc(cc: str) -> tuple:
    """
    Check if CC is valid
    Returns (status: str, response: str)
    """
    # Remove any whitespace and validate format
    cc = cc.strip()
    if not re.match(r'^\d{16}[|\s]?\d{2}[|\s]?\d{2}[|\s]?\d{3,4}$', cc):
        return "error", "Invalid CC format"
    
    # Example API call - replace with actual implementation
    try:
        async with aiohttp.ClientSession() as session:
            # Replace with your actual API endpoint and parameters
            payload = {"cc": cc}
            async with session.post(CC_CHECK_API, json=payload, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Parse response based on your API
                    if data.get("status") == "approved":
                        return "approved", data.get("response", "CC is valid")
                    else:
                        return "declined", data.get("response", "CC is invalid")
                else:
                    return "error", f"API error: {resp.status}"
    except Exception as e:
        logger.error(f"Error checking CC: {e}")
        return "error", f"Connection error: {str(e)}"

# Start command
@dp.message(Command("start"))
async def cmd_start(message: Message):
    welcome_text = """
🎉 *Welcome to CC Checker Bot* 🎉

*Available Commands:*

👑 *Owner Only:*
• `/approve <userid>` - Approve a user to use the bot
• `/disapprove <userid>` - Remove user's access

✅ *Approved Users:*
• `/st` - Check a single credit card
• `/stxt` - Reply to a file with CCs (one per line) to check multiple cards
• `/stop` - Stop the current file checking process

📝 *Format Examples:*
• Single CC: `4111111111111111|12|25|123`
• File: One CC per line

🔒 *This bot is for authorized users only*

*Made with ❤️ using Python and aiogram*
"""
    await message.reply(welcome_text, parse_mode="Markdown")

# Approve user (owner only)
@dp.message(Command("approve"))
async def cmd_approve(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ This command is only for bot owner!")
        return
    
    args = message.text.split()
    if len(args) != 2:
        await message.reply("❌ Usage: `/approve <userid>`", parse_mode="Markdown")
        return
    
    try:
        user_id = int(args[1])
        approved_users.add(user_id)
        await message.reply(f"✅ User `{user_id}` has been approved!", parse_mode="Markdown")
    except ValueError:
        await message.reply("❌ Invalid user ID!")

# Disapprove user (owner only)
@dp.message(Command("disapprove"))
async def cmd_disapprove(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ This command is only for bot owner!")
        return
    
    args = message.text.split()
    if len(args) != 2:
        await message.reply("❌ Usage: `/disapprove <userid>`", parse_mode="Markdown")
        return
    
    try:
        user_id = int(args[1])
        approved_users.discard(user_id)
        await message.reply(f"❌ User `{user_id}` has been disapproved!", parse_mode="Markdown")
    except ValueError:
        await message.reply("❌ Invalid user ID!")

# Check single CC
@dp.message(Command("st"))
async def cmd_st(message: Message):
    # Check if user is approved
    if message.from_user.id not in approved_users and message.from_user.id != OWNER_ID:
        await message.reply("❌ You are not authorized to use this bot!")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) != 2:
        await message.reply("❌ Usage: `/st <cc_details>`\nExample: `4111111111111111|12|25|123`", parse_mode="Markdown")
        return
    
    cc = args[1]
    status_msg = await message.reply("🔄 *Checking CC...*", parse_mode="Markdown")
    
    status, response = await check_cc(cc)
    
    if status == "approved":
        await status_msg.edit_text(f"✅ *APPROVED*\n`{cc}`\n📝 Response: {response}", parse_mode="Markdown")
    elif status == "declined":
        await status_msg.edit_text(f"❌ *DECLINED*\n`{cc}`\n📝 Response: {response}", parse_mode="Markdown")
    else:
        await status_msg.edit_text(f"⚠️ *ERROR*\n`{cc}`\n📝 Response: {response}", parse_mode="Markdown")

# Stop command
@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    user_id = message.from_user.id
    
    if user_id in active_checks and not active_checks[user_id].done():
        stop_flags[user_id] = True
        await message.reply("🛑 *Stopping the check process...*\nThis may take a moment.", parse_mode="Markdown")
    else:
        await message.reply("ℹ️ No active check process found for you.")

# Process file with CCs
@dp.message(Command("stxt"))
async def cmd_stxt(message: Message):
    # Check if user is approved
    if message.from_user.id not in approved_users and message.from_user.id != OWNER_ID:
        await message.reply("❌ You are not authorized to use this bot!")
        return
    
    # Check if replying to a file
    if not message.reply_to_message or not message.reply_to_message.document:
        await message.reply("❌ Please reply to a file containing CCs!\nUsage: Reply to a .txt file with `/stxt`")
        return
    
    # Check if user already has an active check
    user_id = message.from_user.id
    if user_id in active_checks and not active_checks[user_id].done():
        await message.reply("⚠️ You already have an active check process!\nUse `/stop` to stop it first.")
        return
    
    # Reset stop flag
    stop_flags[user_id] = False
    
    # Send initial message
    status_msg = await message.reply("📥 *Downloading and processing file...*", parse_mode="Markdown")
    
    # Download file
    file = await bot.get_file(message.reply_to_message.document.file_id)
    file_path = f"temp_{user_id}.txt"
    await bot.download_file(file.file_path, file_path)
    
    # Read CCs from file
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            ccs = [line.strip() for line in f if line.strip()]
        
        if not ccs:
            await status_msg.edit_text("❌ No valid CCs found in the file!")
            os.remove(file_path)
            return
        
        total = len(ccs)
        await status_msg.edit_text(f"📊 *File loaded*\nTotal CCs: `{total}`\n🔄 *Starting check...*", parse_mode="Markdown")
        
        # Start checking process
        task = asyncio.create_task(process_ccs(user_id, ccs, status_msg))
        active_checks[user_id] = task
        
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        await status_msg.edit_text(f"❌ Error reading file: {str(e)}")
        if os.path.exists(file_path):
            os.remove(file_path)

async def process_ccs(user_id: int, ccs: list, status_msg: Message):
    """Process all CCs in the file"""
    total = len(ccs)
    approved_count = 0
    declined_count = 0
    error_count = 0
    approved_ccs = []
    current = 0
    
    # Initial status message
    await update_status_message(status_msg, current, total, approved_count, declined_count, error_count, None)
    
    for cc in ccs:
        # Check if stop requested
        if stop_flags.get(user_id, False):
            await status_msg.edit_text(
                f"🛑 *Process Stopped by User*\n\n"
                f"📊 *Final Summary:*\n"
                f"• Total CCs: `{total}`\n"
                f"• Processed: `{current}`\n"
                f"• ✅ Approved: `{approved_count}`\n"
                f"• ❌ Declined: `{declined_count}`\n"
                f"• ⚠️ Error: `{error_count}`\n\n"
                f"Stopped at user request.",
                parse_mode="Markdown"
            )
            break
        
        current += 1
        status, response = await check_cc(cc)
        
        # Update counters
        if status == "approved":
            approved_count += 1
            approved_ccs.append(f"✅ `{cc}` - {response}")
            # Send approved CC immediately
            try:
                await bot.send_message(
                    user_id,
                    f"✅ *APPROVED CC FOUND!*\n`{cc}`\n📝 Response: {response}",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Error sending approved CC: {e}")
        elif status == "declined":
            declined_count += 1
        else:
            error_count += 1
        
        # Update status message every 5 CCs or at the end
        if current % 5 == 0 or current == total:
            await update_status_message(status_msg, current, total, approved_count, declined_count, error_count, None)
        
        # Small delay to avoid overwhelming API
        await asyncio.sleep(0.5)
    
    # Send final summary
    if not stop_flags.get(user_id, False):
        final_summary = (
            f"✅ *File Check Completed!*\n\n"
            f"📊 *Final Summary:*\n"
            f"• Total CCs: `{total}`\n"
            f"• ✅ Approved: `{approved_count}`\n"
            f"• ❌ Declined: `{declined_count}`\n"
            f"• ⚠️ Error: `{error_count}`\n\n"
            f"📝 *Approved CCs:*\n" + "\n".join(approved_ccs[:10]) + 
            (f"\n... and {len(approved_ccs) - 10} more" if len(approved_ccs) > 10 else "")
        )
        
        await status_msg.edit_text(final_summary, parse_mode="Markdown")
        
        # Send full list of approved CCs if there are many
        if len(approved_ccs) > 10:
            full_list = "📝 *All Approved CCs:*\n" + "\n".join(approved_ccs)
            # Split into multiple messages if needed
            for i in range(0, len(full_list), 4000):
                await bot.send_message(user_id, full_list[i:i+4000], parse_mode="Markdown")
    
    # Cleanup
    if os.path.exists(f"temp_{user_id}.txt"):
        os.remove(f"temp_{user_id}.txt")
    
    # Remove from active checks
    if user_id in active_checks:
        del active_checks[user_id]
    if user_id in stop_flags:
        del stop_flags[user_id]

async def update_status_message(msg: Message, current: int, total: int, approved: int, declined: int, error: int, last_cc: str = None):
    """Update the status message with current progress"""
    progress = (current / total) * 100
    status_text = (
        f"🔄 *Checking CCs...*\n\n"
        f"📊 *Progress:*\n"
        f"• Processed: `{current}/{total}`\n"
        f"• Progress: `{progress:.1f}%`\n\n"
        f"📈 *Results:*\n"
        f"• ✅ Approved: `{approved}`\n"
        f"• ❌ Declined: `{declined}`\n"
        f"• ⚠️ Error: `{error}`\n\n"
        f"💡 *Tip:* Use `/stop` to stop the process\n\n"
        f"📝 *Live approved CCs will appear in chat*"
    )
    
    try:
        await msg.edit_text(status_text, parse_mode="Markdown")
    except Exception as e:
        # If editing fails, send new message
        logger.error(f"Error updating message: {e}")

# Admin command to list approved users
@dp.message(Command("listusers"))
async def cmd_listusers(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply("❌ This command is only for bot owner!")
        return
    
    if not approved_users:
        await message.reply("ℹ️ No approved users yet.")
    else:
        users_list = "\n".join([f"• `{uid}`" for uid in approved_users])
        await message.reply(f"✅ *Approved Users:*\n{users_list}", parse_mode="Markdown")

# Error handler
@dp.errors()
async def error_handler(update: types.Update, exception: Exception):
    logger.error(f"Error occurred: {exception}", exc_info=True)
    if update.message:
        await update.message.reply("⚠️ An error occurred. Please try again later.")

# Main function to start the bot
async def main():
    # Load approved users from file if exists
    if os.path.exists("approved_users.txt"):
        try:
            with open("approved_users.txt", "r") as f:
                for line in f:
                    if line.strip():
                        approved_users.add(int(line.strip()))
            logger.info(f"Loaded {len(approved_users)} approved users")
        except Exception as e:
            logger.error(f"Error loading approved users: {e}")
    
    # Start the bot
    logger.info("Starting bot...")
    await dp.start_polling(bot)

# Save approved users periodically
async def save_approved_users():
    while True:
        await asyncio.sleep(60)  # Save every minute
        try:
            with open("approved_users.txt", "w") as f:
                for user_id in approved_users:
                    f.write(f"{user_id}\n")
        except Exception as e:
            logger.error(f"Error saving approved users: {e}")

if __name__ == "__main__":
    # Run save task in background
    loop = asyncio.get_event_loop()
    loop.create_task(save_approved_users())
    
    # Run main bot
    asyncio.run(main())