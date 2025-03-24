"""Auto Forward Messages"""
from argparse import ArgumentParser, BooleanOptionalAction
from pyrogram.errors import MessageIdInvalid, FloodWait, UsernameNotOccupied, PeerIdInvalid, ChannelInvalid
from pyrogram.types import ChatPrivileges
from configparser import ConfigParser
from pyrogram.enums import ParseMode
from pyrogram import Client
import time
import json
import os
import re
import logging
from pathlib import Path

# Configure logging - Fix the format string by correcting levelname syntax
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def is_chat_id(chat):
    if chat is None:
        return False
    # Support more formats: -100 channels (with any number of digits), regular IDs, and username-like strings
    return bool(re.match(r'^(-100)\d+$', str(chat)) or  # Channel/supergroup - updated to handle longer IDs
                re.match(r'^\d+$', str(chat)) or  # User/bot/private channel
                re.match(r'^-\d+$', str(chat)))  # Group

def convert_channel_id(chat_id):
    """Convert channel IDs to the format Pyrogram can understand
    
    Newer channel IDs might have an extra digit that needs to be handled differently
    """
    if isinstance(chat_id, str) and chat_id.startswith('-100'):
        # Convert string format to integer by removing first 4 chars (-100)
        # and converting the rest to int (this is what Pyrogram expects)
        try:
            raw_id = int(chat_id[4:])
            logger.info(f"Converting channel ID from {chat_id} to raw format: {raw_id}")
            return raw_id
        except ValueError:
            logger.error(f"Failed to convert channel ID: {chat_id}")
            return chat_id
    return chat_id

def extract_chat_id_from_link(link):
    """Extract channel username or ID from various telegram links"""
    if link is None:
        return None
    
    # Handle t.me links, telegram.me, or direct usernames
    username_match = re.search(r't\.me/(?:joinchat/)?([^/?]+)|telegram\.me/(?:joinchat/)?([^/?]+)|@?([a-zA-Z]\w{3,30}[a-zA-Z\d])$', link)
    if username_match:
        # Return the first non-None group
        return next((group for group in username_match.groups() if group is not None), None)
    
    # Try direct ID (already handled by is_chat_id)
    return link if is_chat_id(link) else None

def check_chat_id(client, chat_id):
    """Check if a chat ID is valid and accessible"""
    try:
        chat_obj = client.get_chat(chat_id)
        if hasattr(chat_obj, 'title'):
            return chat_obj.title, chat_obj.id
        else:
            # For private chats that don't have a title
            name = ""
            if hasattr(chat_obj, 'first_name'):
                name = f"{chat_obj.first_name or ''} {chat_obj.last_name or ''}".strip()
            return name, chat_obj.id
    except ChannelInvalid:
        logger.error(f"Non-accessible chat: {chat_id}. Make sure you are a member of this chat.")
        return None, None
    except PeerIdInvalid:
        logger.error(f"Invalid chat ID or username: {chat_id}")
        return None, None
    except UsernameNotOccupied:
        logger.error(f"Username not found: {chat_id}")
        return None, None
    except Exception as e:
        logger.error(f"Error checking chat: {chat_id}. Error: {e}")
        return None, None

def get_chats(client, bot_id):
    global from_chat, to_chat, chats
    logger.info(f"Trying to resolve chats - From: {from_chat}, To: {to_chat}")
    
    try:
        # Try to extract username or ID if it's a link
        from_chat_id = extract_chat_id_from_link(from_chat)
        logger.info(f"Extracted from_chat_id: {from_chat_id}")
        
        # Try to get chat info
        from_chat_title, from_chat_resolved_id = None, None
        try:
            if is_chat_id(from_chat_id):
                # If it's a new format channel ID (-100...), convert it properly
                if str(from_chat_id).startswith('-100'):
                    chat_id_to_use = convert_channel_id(from_chat_id)
                    logger.info(f"Using converted channel ID: {chat_id_to_use}")
                    from_chat_title, from_chat_resolved_id = check_chat_id(client, chat_id_to_use)
                else:
                    from_chat_title, from_chat_resolved_id = check_chat_id(client, int(from_chat_id))
                logger.info(f"Found chat by ID: {from_chat_resolved_id}")
            else:
                # Handle username (remove @ if present)
                username = from_chat_id.lstrip('@') if from_chat_id else from_chat.lstrip('@')
                from_chat_title, from_chat_resolved_id = check_chat_id(client, username)
                logger.info(f"Found chat by username: {from_chat_resolved_id}")
                
            if from_chat_resolved_id is None:
                raise ValueError(f"Could not find origin chat: {from_chat}")
                
            chats["from_chat_id"] = from_chat_resolved_id
            logger.info(f"Origin chat resolved: ID={from_chat_resolved_id}, Title={from_chat_title}")
        except (ValueError, PeerIdInvalid, UsernameNotOccupied) as e:
            logger.error(f"Error getting origin chat: {e}")
            logger.error(f"Additional info - Chat ID format used: {from_chat_id}")
            if str(from_chat_id).startswith('-100'):
                logger.error(f"This appears to be a channel ID. Tried with format: {convert_channel_id(from_chat_id)}")
            raise ValueError(f"Could not find origin chat: {from_chat}. Error: {e}")
        
        # Handle destination chat
        if to_chat:
            to_chat_id = extract_chat_id_from_link(to_chat)
            logger.info(f"Extracted to_chat_id: {to_chat_id}")
            
            try:
                to_chat_title, to_chat_resolved_id = None, None
                if is_chat_id(to_chat_id):
                    # If it's a new format channel ID (-100...), convert it properly
                    if str(to_chat_id).startswith('-100'):
                        chat_id_to_use = convert_channel_id(to_chat_id)
                        logger.info(f"Using converted channel ID: {chat_id_to_use}")
                        to_chat_title, to_chat_resolved_id = check_chat_id(client, chat_id_to_use)
                    else:
                        to_chat_title, to_chat_resolved_id = check_chat_id(client, int(to_chat_id))
                    logger.info(f"Found destination chat by ID: {to_chat_resolved_id}")
                else:
                    # Handle username (remove @ if present)
                    username = to_chat_id.lstrip('@') if to_chat_id else to_chat.lstrip('@')
                    to_chat_title, to_chat_resolved_id = check_chat_id(client, username)
                    logger.info(f"Found destination chat by username: {to_chat_resolved_id}")
                
                if to_chat_resolved_id is None:
                    raise ValueError(f"Could not find destination chat: {to_chat}")
                    
                chats["to_chat_id"] = to_chat_resolved_id
                logger.info(f"Destination chat resolved: ID={to_chat_resolved_id}")
            except (ValueError, PeerIdInvalid, UsernameNotOccupied) as e:
                logger.error(f"Error getting destination chat: {e}")
                logger.error(f"Additional info - Chat ID format used: {to_chat_id}")
                if str(to_chat_id).startswith('-100'):
                    logger.error(f"This appears to be a channel ID. Tried with format: {convert_channel_id(to_chat_id)}")
                raise ValueError(f"Could not find destination chat: {to_chat}. Error: {e}")
        else:
            # Create destination channel if none provided
            logger.info(f"Creating new destination channel named '{from_chat_title}-clone'")
            dest = client.create_channel(title=f'{from_chat_title}-clone')
            chats["to_chat_id"] = dest.id
            logger.info(f"Created destination channel with ID: {chats['to_chat_id']}")
        
        # Bot mode permissions
        if mode == "bot" and bot_id not in ('bot_id:none', ''):
            bot_numeric_id = int(bot_id.replace('bot_id:', ''))
            logger.info(f"Setting bot permissions for bot_id: {bot_numeric_id}")
            for chat_id in [chats["from_chat_id"], chats["to_chat_id"]]:
                try:
                    client.promote_chat_member(
                        privileges=ChatPrivileges(can_post_messages=True),
                        chat_id=chat_id,
                        user_id=bot_numeric_id
                    )
                    logger.info(f"Bot promoted in chat {chat_id}")
                except Exception as e:
                    logger.warning(f"Could not promote bot in chat {chat_id}: {e}")
                    
    except FloodWait as e:
        logger.warning(f"Hit Telegram rate limit. Waiting {e.value} seconds...")
        time.sleep(e.value)
        get_chats(client, bot_id)  # Retry after waiting
    except Exception as e:
        logger.error(f"Unexpected error in get_chats: {e}", exc_info=True)
        raise

def ensure_connection(client_name, api_id=None, api_hash=None, bot_token=None):
    """Ensure valid connection to Telegram API, creating or reusing session files"""
    logger.info(f"Ensuring connection for {client_name}...")
    
    if client_name == "user":
        if Path(f"{client_name}.session").exists():
            try:
                client = Client(client_name)
                client.start()
                logger.info(f"Connected using existing session: {client_name}")
                return client
            except Exception as e:
                logger.error(f"Error using existing session: {e}")
                logger.warning("Using provided API credentials instead")
        
        if api_id and api_hash:
            try:
                client = Client(client_name, api_id=api_id, api_hash=api_hash)
                client.start()
                logger.info(f"Connected as user with provided API credentials")
                return client
            except Exception as e:
                logger.error(f"Error connecting with provided credentials: {e}")
                raise
    
    elif client_name == "bot":
        if Path(f"{client_name}.session").exists() and not (api_id and api_hash and bot_token):
            try:
                client = Client(client_name)
                client.start()
                logger.info(f"Connected using existing bot session")
                return client
            except Exception as e:
                logger.error(f"Error using existing bot session: {e}")
                logger.warning("Will try using provided API credentials")
        
        if api_id and api_hash and bot_token:
            try:
                client = Client(client_name, api_id=api_id, api_hash=api_hash, bot_token=bot_token)
                client.start()
                logger.info(f"Connected as bot with provided credentials")
                return client
            except Exception as e:
                logger.error(f"Error connecting with provided bot credentials: {e}")
                raise
    
    logger.error(f"Failed to establish connection for {client_name}")
    raise ValueError(f"Could not establish connection for {client_name}")

def connect_to_api(api_id, api_hash, bot_token):
    try:
        logger.info("Connecting to Telegram API as user...")
        client = Client('user', api_id=api_id, api_hash=api_hash)
        bot_id = 'bot_id:none'
        
        with client:
            user_id = client.get_me().id
            logger.info(f"Connected as user: {user_id}")
            client.send_message(
                user_id, "Message sent with **Auto Forward Messages**!"
            )
        
        if bot_token:
            logger.info("Connecting to Telegram API as bot...")
            bot_client = Client(
                'bot', api_id=api_id, api_hash=api_hash, bot_token=bot_token
            )
            
            with bot_client:
                bot_id_num = bot_token.split(':')[0]
                bot_id = f'bot_id:{bot_id_num}'
                bot_client.send_message(
                    user_id, "Message sent with **Auto Forward Messages**!"
                )
                logger.info(f"Connected as bot: {bot_id}")
        
        # Create default configuration
        data = f"[default]\n{bot_id}\nuser_delay_seconds:10\nbot_delay_seconds:5\nskip_delay_seconds:1"
        with open('config.ini', 'w') as f:
            f.write(data)
        
        # Initialize configs dictionary with default values
        configs["bot_id"] = bot_id
        configs["user_delay_seconds"] = 10.0
        configs["bot_delay_seconds"] = 5.0
        configs["skip_delay_seconds"] = 1.0
        
        return client, bot_id
    except Exception as e:
        logger.error(f"Error connecting to API: {e}", exc_info=True)
        raise

def is_empty_message(message) -> bool:
    if message.empty or message.service or message.dice or message.location:
        return True
    return False

def filter_messages(client):
    list_ids=[]
    print("Getting messages...\n")
    try:
        if query == "":
            messages=client.get_chat_history(chats["from_chat_id"])
            messages=[msg for msg in messages if not is_empty_message(msg)]
        else:
            messages=client.search_messages(
                chats["from_chat_id"], query=query
            )
        
        if filter:
            for message in messages:
                if message.media:
                    msg_media=str(message.media)
                    msg_type=msg_media.replace('MessageMediaType.','')
                    if msg_type.lower() in filter:
                        list_ids.append(message.id)
                if message.text and "text" in filter:
                    list_ids.append(message.id)
                if message.poll and "poll" in filter:
                    list_ids.append(message.id)
        else:
            list_ids=[message.id for message in messages]
    except Exception as e:
        logger.error(f"Error filtering messages: {e}", exc_info=True)
        raise

    return list_ids

def get_ids(client):
    global CACHE_FILE
    
    try:
        total = client.get_chat_history_count(chats["from_chat_id"])
        if total > 25000:
            print(
                "Warning: The origin chat contains a large number of messages.\n"+
                "It is recommended to forward up to 1000 messages per day.\n"
            )
        chat_ids = filter_messages(client)
        chat_ids.sort()
        
        # Ensure the posteds directory exists
        os.makedirs('posteds', exist_ok=True)
        
        # Create a unique cache file name based on both chat IDs
        cache = f'{chats["from_chat_id"]}_{chats["to_chat_id"]}.json'
        CACHE_FILE = f'posteds/{cache}'

        # Handle resuming from previous point
        if options.resume and os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as j:
                last_id = json.load(j)
            # Find the index of the last processed message
            last_ids = [i for i in chat_ids if i <= last_id]
            if last_ids:
                last_id = last_ids[-1]
                n = chat_ids.index(last_id) + 1
                chat_ids = chat_ids[n:]
                logger.info(f"Resuming from message ID {last_id} (index {n})")
            else:
                logger.info("No previous messages found in the current set to resume from")

        # Apply message limit if specified
        if limit != 0:
            chat_ids = chat_ids[:limit]
            logger.info(f"Limited to {limit} messages")
            
        logger.info(f"Found {len(chat_ids)} messages to forward")
        return chat_ids
    except Exception as e:
        logger.error(f"Error getting message IDs: {e}", exc_info=True)
        raise

def auto_forward(client, chat_ids):
    """Forward messages from source to destination chat with error handling and progress tracking"""
    os.makedirs('posteds', exist_ok=True)
    
    total = len(chat_ids)
    failed = 0
    
    for index, message_id in enumerate(chat_ids):
        try:
            os.system('clear || cls')
            current = index + 1
            print(f"Forwarding: {current}/{total} ({(current/total)*100:.1f}%)")
            
            # Forward message
            client.forward_messages(
                from_chat_id=chats["from_chat_id"],
                chat_id=chats["to_chat_id"],
                message_ids=message_id
            )
            
            # Update cache file with last processed message ID
            with open(CACHE_FILE, "w") as j:
                json.dump(message_id, j)
                
            # Delay between messages if not the last one
            if message_id != chat_ids[-1]:
                time.sleep(delay)
                
        except MessageIdInvalid:
            logger.warning(f"Invalid message ID: {message_id} - skipping")
            failed += 1
            
        except FloodWait as e:
            logger.warning(f"Hit Telegram rate limit. Waiting {e.value} seconds...")
            # Save current progress
            with open(CACHE_FILE, "w") as j:
                json.dump(message_id, j)
            time.sleep(e.value)
            # Try to forward the same message again
            index -= 1
            
        except Exception as e:
            logger.error(f"Error forwarding message {message_id}: {e}", exc_info=True)
            failed += 1
            # Brief pause before continuing
            time.sleep(2)
            
    print(f"\nTask completed! Successfully forwarded {total-failed} messages.")
    if failed > 0:
        print(f"Failed to forward {failed} messages.")

def countdown():
    """Display countdown timer for restart mode"""
    time_sec = 4*3600
    while time_sec:
        mins, secs = divmod(time_sec, 60)
        hours, mins = divmod(mins, 60)
        timeformat = f'{hours:02d}:{mins:02d}:{secs:02d}'
        print('Restarting in:', timeformat, end='\r')
        time.sleep(1)
        time_sec -= 1

def get_full_chat():
    """Main function to get and forward messages"""
    try:
        # Initialize the appropriate client mode
        if mode == "user":
            client = ensure_connection('user')
        else:  # bot mode
            client = ensure_connection('bot')
            
        with client:
            # Get chat information
            get_chats(client, configs.get("bot_id", "bot_id:none"))
            # Get message IDs to forward
            chat_ids = get_ids(client)
            
            # Forward messages
            if chat_ids:
                client.set_parse_mode(ParseMode.DISABLED)
                auto_forward(client, chat_ids)
            else:
                logger.info("No messages to forward")
    except Exception as e:
        logger.error(f"Error in get_full_chat: {e}", exc_info=True)
        raise

def main():
    global delay, configs
    
    try:
        # Set default values for configs
        configs = {
            "user_delay_seconds": 10.0,
            "bot_delay_seconds": 5.0,
            "skip_delay_seconds": 1.0,
            "bot_id": "bot_id:none"
        }
        
        # If API credentials are provided, set up the connection
        if options.api_id:
            _, bot_id = connect_to_api(options.api_id, options.api_hash, options.bot_token)
            configs["bot_id"] = bot_id
        else:
            # Load configuration from file
            if os.path.exists("config.ini"):
                config_data = ConfigParser()
                config_data.read("config.ini")
                if "default" in config_data:
                    config_data = dict(config_data["default"])
                    configs["user_delay_seconds"] = float(config_data.get("user_delay_seconds", "10.0"))
                    configs["bot_delay_seconds"] = float(config_data.get("bot_delay_seconds", "5.0"))
                    configs["skip_delay_seconds"] = float(config_data.get("skip_delay_seconds", "1.0"))
                    configs["bot_id"] = config_data.get("bot_id", "bot_id:none")

        # Set delay based on mode
        delay = configs["user_delay_seconds"] if mode == "user" else configs["bot_delay_seconds"]
        logger.info(f"Using delay of {delay} seconds between messages")

        # Handle restart option or single run
        if options.restart:
            logger.info("Running in continuous mode with periodic restarts")
            while True:
                get_full_chat()
                countdown()
        else:
            logger.info("Running in single execution mode")
            get_full_chat()
            
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
    except Exception as e:
        logger.error(f"Error in main function: {e}", exc_info=True)
        raise

# Parse command line arguments
os.system('clear || cls')
parser = ArgumentParser()
parser.add_argument(
    "-m","--mode",choices=["user", "bot"],default="user",
    help="'user'=forward in user mode,'bot'=forward in bot mode"
)
parser.add_argument(
    "-R","--restart", action=BooleanOptionalAction,
    help="The program will restart searching for new messages on origin chat."
)
parser.add_argument("-o","--orig",help="Origin chat id, username, or link")
parser.add_argument("-d","--dest",help="Destination chat id, username, or link")
parser.add_argument("-q","--query",type=str,default="",help="Query string to filter messages")
parser.add_argument("-r","--resume", action=BooleanOptionalAction,help="Resume task from last forwarded message")
parser.add_argument("-l","--limit",type=int,default=0,help="Max number of messages to forward")
parser.add_argument("-f","--filter",type=str,default=None,help="Filter messages by type (photo,text,document,etc)")
parser.add_argument('-i','--api-id',type=int,help="Api id")
parser.add_argument('-s','--api-hash',type=str,help="Api hash")
parser.add_argument('-b','--bot-token',type=str,help="Token of a bot")
options = parser.parse_args()

# Initialize global variables
configs = {}
chats = {}
CACHE_FILE = None
delay = 10.0  # Default delay if not set

from_chat = options.orig
to_chat = options.dest
mode = options.mode
query = options.query
limit = options.limit
filter = options.filter
filter = filter.split(",") if filter else None

if __name__=="__main__":
    main()
