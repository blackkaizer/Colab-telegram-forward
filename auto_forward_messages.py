"""Auto Forward Messages"""
from argparse import ArgumentParser, BooleanOptionalAction
from pyrogram.errors import MessageIdInvalid, FloodWait, UsernameNotOccupied, PeerIdInvalid
from pyrogram.types import ChatPrivileges
from configparser import ConfigParser
from pyrogram.enums import ParseMode
from pyrogram import Client
import time
import json
import os
import re
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def is_chat_id(chat):
    if chat is None:
        return False
    # Support more formats: -100 channels, regular IDs, and username-like strings
    return bool(re.match(r'^(-100)\d+$', str(chat)) or  # Channel/supergroup
                re.match(r'^\d+$', str(chat)) or  # User/bot/private channel
                re.match(r'^-\d+$', str(chat)))  # Group

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

def get_chats(client, bot_id):
    global from_chat, to_chat
    logger.info(f"Trying to resolve chats - From: {from_chat}, To: {to_chat}")
    
    try:
        # Try to extract username or ID if it's a link
        from_chat_id = extract_chat_id_from_link(from_chat)
        logger.info(f"Extracted from_chat_id: {from_chat_id}")
        
        # Try to get chat info
        try:
            if is_chat_id(from_chat_id):
                chat = client.get_chat(int(from_chat_id))
                logger.info(f"Found chat by ID: {chat.id}")
            else:
                # Handle username (remove @ if present)
                username = from_chat_id.lstrip('@') if from_chat_id else from_chat
                chat = client.get_chat(username)
                logger.info(f"Found chat by username: {chat.id}")
        except (ValueError, PeerIdInvalid, UsernameNotOccupied) as e:
            logger.error(f"Error getting origin chat: {e}")
            raise ValueError(f"Could not find origin chat: {from_chat}. Error: {e}")
            
        # Get chat title or name
        name = ""
        if hasattr(chat, 'first_name'):
            name = f"{chat.first_name or ''} {chat.last_name or ''}".strip()
        chat_title = getattr(chat, 'title', None)
        chats["from_chat_id"] = chat.id
        from_chat_title = chat_title if chat_title else name
        logger.info(f"Origin chat resolved: ID={chat.id}, Title={from_chat_title}")
        
        # Handle destination chat
        if to_chat:
            to_chat_id = extract_chat_id_from_link(to_chat)
            logger.info(f"Extracted to_chat_id: {to_chat_id}")
            
            try:
                if is_chat_id(to_chat_id):
                    to_chat_info = client.get_chat(int(to_chat_id))
                    chats["to_chat_id"] = to_chat_info.id
                else:
                    username = to_chat_id.lstrip('@') if to_chat_id else to_chat
                    to_chat_info = client.get_chat(username)
                    chats["to_chat_id"] = to_chat_info.id
                logger.info(f"Destination chat resolved: ID={chats['to_chat_id']}")
            except (ValueError, PeerIdInvalid, UsernameNotOccupied) as e:
                logger.error(f"Error getting destination chat: {e}")
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

def connect_to_api(api_id, api_hash, bot_token):
    try:
        logger.info("Connecting to Telegram API as user...")
        client = Client('user', api_id=api_id, api_hash=api_hash)
        with client:
            user_id = client.get_me().id
            logger.info(f"Connected as user: {user_id}")
            client.send_message(
                user_id, "Message sent with **Auto Forward Messages**!"
            )
        
        if bot_token:
            logger.info("Connecting to Telegram API as bot...")
            client = Client(
                'bot', api_id=api_id, api_hash=api_hash, bot_token=bot_token
            )
            bot_id = bot_token[:bot_token.find(':')]
            bot_id = f'bot_id:{bot_id}'
            with client:
                client.send_message(
                    user_id, "Message sent with **Auto Forward Messages**!"
                )
                logger.info(f"Connected as bot: {bot_id}")
        else:
            bot_id = 'bot_id:none'
        
        data = f"[default]\n{bot_id}\nuser_delay_seconds:10\nbot_delay_seconds:5"
        with open('config.ini', 'w') as f:
            f.write(data)
        
        return client
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

    return list_ids

def get_ids(client):
    global CACHE_FILE
    total=client.get_chat_history_count(chats["from_chat_id"])
    if total > 25000:print(
        "Warning: The origin chat contains a large number of messages.\n"+
        "It is recommended to forward up to 1000 messages per day.\n"
    )
    chat_ids=filter_messages(client)
    chat_ids.sort()
    cache =f'{chats["from_chat_id"]}_{chats["to_chat_id"]}.json'
    CACHE_FILE=f'posteds/{cache}'

    if options.resume and os.path.exists(CACHE_FILE):
        with open(CACHE_FILE,"r") as j:
            last_id = json.load(j)
        last_id = [i for i in chat_ids if i <= last_id][-1]
        n=chat_ids.index(last_id)+1
        chat_ids=chat_ids[n:]

    if limit != 0:
        chat_ids=chat_ids[:limit]

    return chat_ids

def auto_forward(client,chat_ids):
    os.makedirs('posteds',exist_ok=True)
    for message_id in chat_ids:
        try:
            os.system('clear || cls')
            print(f"Forwarding: {chat_ids.index(message_id)+1}/{len(chat_ids)}")
            client.forward_messages(
                from_chat_id=chats["from_chat_id"],
                chat_id=chats["to_chat_id"],
                message_ids=message_id
            )
            with open(CACHE_FILE,"w") as j:
                json.dump(message_id,j)
            if message_id != chat_ids[-1]:
                time.sleep(delay)
        except MessageIdInvalid:
            pass
    print("\nTask completed!\n")

def countdown():
    time_sec = 4*3600
    while time_sec:
        mins, secs = divmod(time_sec, 60)
        hours, mins = divmod(mins, 60)
        timeformat = f'{hours:02d}:{mins:02d}:{secs:02d}'
        print('Restarting in:',timeformat, end='\r')
        time.sleep(1)
        time_sec -= 1

def get_full_chat():
    client=Client('user',takeout=True)
    with client:
        get_chats(client,configs["bot_id"])
        chat_ids=get_ids(client)
    app=Client(mode)
    app.set_parse_mode(ParseMode.DISABLED)
    with app:
        auto_forward(app,chat_ids)

def main():
    global delay
    if options.api_id:
        connect_to_api(options.api_id,options.api_hash,options.bot_token)
    else:
        config_data = ConfigParser()
        config_data.read("config.ini")
        config_data = dict(config_data["default"])
        configs["user_delay_seconds"]=float(config_data["user_delay_seconds"])
        configs["bot_delay_seconds"]=float(config_data["bot_delay_seconds"])
        configs["bot_id"]=config_data["bot_id"]

        delay=configs["user_delay_seconds"] if mode == "user"\
        else configs["bot_delay_seconds"]

        if options.restart:
            while True:
                get_full_chat()
                countdown()
        else:
            get_full_chat()

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
parser.add_argument("-o","--orig",help="Origin chat id")
parser.add_argument("-d","--dest",help="Destination chat id")
parser.add_argument("-q","--query",type=str,default="",help="Query sting")
parser.add_argument("-r","--resume", action=BooleanOptionalAction,help="Resume task")
parser.add_argument("-l","--limit",type=int,default=0,help="Max number of messages to forward")
parser.add_argument("-f","--filter",type=str,default=None,help="Filter messages by kind")
parser.add_argument('-i','--api-id',type=int,help="Api id")
parser.add_argument('-s','--api-hash',type=str,help="Api hash")
parser.add_argument('-b','--bot-token',type=str,help="Token of a bot")
options = parser.parse_args()

configs={}
chats={}

from_chat=options.orig
to_chat=options.dest
mode=options.mode
query=options.query
limit=options.limit
filter = options.filter
filter=filter.split(",") if\
filter else None

if __name__=="__main__":
    main()
