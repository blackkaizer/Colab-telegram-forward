"""Auto Forward Messages"""
from argparse import ArgumentParser, BooleanOptionalAction
from pyrogram.errors import MessageIdInvalid
from pyrogram.types import ChatPrivileges
from configparser import ConfigParser
from pyrogram.enums import ParseMode
from pyrogram import Client
import time
import json
import os
import re


def is_chat_id(chat):
    chat = str(chat)
    if chat.startswith('-100') and chat[4:].isdigit():
        return True
    if chat.isdigit():
        return True
    if chat.startswith('@'):  # Adicionei a verificação se é um username
        return True
    return False


def get_chats(client, bot_id):
    try:
        if is_chat_id(from_chat):
            chats["from_chat_id"] = int(from_chat) if from_chat.isdigit() else int(from_chat)  #garante que o id será int
            from_chat_obj = client.get_chat(chats["from_chat_id"])
        else:
            from_chat_obj = client.get_chat(from_chat)  # Assume username
            chats["from_chat_id"] = from_chat_obj.id

        from_chat_title = from_chat_obj.title if from_chat_obj.title else f"{from_chat_obj.first_name} {from_chat_obj.last_name}"

        if is_chat_id(to_chat):
            chats["to_chat_id"] = int(to_chat) if to_chat.isdigit() else int(to_chat)  #garante que o id será int
        else:
            to_chat_obj = client.get_chat(to_chat)
            chats["to_chat_id"] = to_chat_obj.id

        if mode == "bot":
            for chat_id in [chats["from_chat_id"], chats["to_chat_id"]]:
                try:
                    client.promote_chat_member(
                        chat_id=chat_id,
                        user_id=bot_id,
                        privileges=ChatPrivileges(can_post_messages=True),
                    )
                except Exception as e:
                    print(f"Erro ao promover o bot em {chat_id}: {e}")  # Tratamento de erro

    except Exception as e:
        print(f"Erro ao obter chats: {e}")
        exit()  # Encerra o programa caso haja erro ao obter os chats


def connect_to_api(api_id, api_hash, bot_token):
    client = Client('user', api_id=api_id, api_hash=api_hash)
    with client:
        user_id = client.get_users('me').id
        # Opcional: Enviar mensagem de teste
        # client.send_message(user_id, "Message sent with **Auto Forward Messages**!")

    if bot_token:
        client = Client(
            'bot', api_id=api_id, api_hash=api_hash, bot_token=bot_token
        )
        bot_id = bot_token[:bot_token.find(':')]
        bot_id = f'bot_id:{bot_id}'
        with client:
            pass
            # Opcional: Enviar mensagem de teste
            # client.send_message(user_id, "Message sent with **Auto Forward Messages**!")
    else:
        bot_id = 'bot_id:none'
    return client, bot_id


def is_empty_message(message) -> bool:
    if message.empty or message.service or message.dice or message.location:
        return True
    return False


def filter_messages(client):
    list_ids = []
    print("Getting messages...\n")

    messages = client.search_messages(chats["from_chat_id"], query=query)

    for message in messages:
        if is_empty_message(message):
            continue  # Pula mensagens vazias

        if filter:
            if message.media:
                msg_media = str(message.media)
                msg_type = msg_media.replace('MessageMediaType.', '').lower()
                if msg_type in filter:
                    list_ids.append(message.id)
            if message.text and "text" in filter:
                list_ids.append(message.id)
            if message.poll and "poll" in filter:
                list_ids.append(message.id)
        else:
            list_ids.append(message.id)

    return list_ids


def get_ids(client):
    global CACHE_FILE
    total = client.get_chat_history_count(chats["from_chat_id"])
    if total > 25000:
        print(
            "Warning: The origin chat contains a large number of messages.\n"
            + "It is recommended to forward up to 1000 messages per day.\n"
        )
    chat_ids = filter_messages(client)
    chat_ids.sort()
    cache = f'{chats["from_chat_id"]}_{chats["to_chat_id"]}.json'
    CACHE_FILE = f'posteds/{cache}'

    if options.resume and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as j:
                last_id = json.load(j)
            if last_id in chat_ids:  # Verifica se last_id existe em chat_ids
                n = chat_ids.index(last_id) + 1
                chat_ids = chat_ids[n:]
            else:  # Se não existir, começa do início
                print("Last ID not found, starting from the beginning.")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Erro ao ler o cache: {e}. Começando do início.")

    if limit != 0:
        chat_ids = chat_ids[:limit]

    return chat_ids


def auto_forward(client, chat_ids):
    os.makedirs('posteds', exist_ok=True)
    success_count = 0
    for message_id in chat_ids:
        try:
            os.system('clear || cls')
            print(f"Forwarding: {chat_ids.index(message_id) + 1}/{len(chat_ids)}")
            client.forward_messages(
                from_chat_id=chats["from_chat_id"],
                chat_id=chats["to_chat_id"],
                message_ids=message_id
            )
            with open(CACHE_FILE, "w") as j:
                json.dump(message_id, j)
            success_count += 1  # Incrementa o contador
            if message_id != chat_ids[-1]:
                time.sleep(delay)
        except MessageIdInvalid:
            pass
    print(f"\nTask completed! {success_count} messages forwarded.\n")


def countdown():
    time_sec = 4 * 3600
    while time_sec:
        mins, secs = divmod(time_sec, 60)
        hours, mins = divmod(mins, 60)
        timeformat = f'{hours:02d}:{mins:02d}:{secs:02d}'
        print('Restarting in:', timeformat, end='\r')
        time.sleep(1)
        time_sec -= 1


def get_full_chat():
    # Cuidado com takeout sessions! Use com moderação.
    client = Client('user', takeout=True)
    with client:
        get_chats(client, configs["bot_id"])
        chat_ids = get_ids(client)
    app = Client(mode)
    app.set_parse_mode(ParseMode.DISABLED)
    with app:
        auto_forward(app, chat_ids)


if __name__ == "__main__":
    os.system('clear || cls')
    parser = ArgumentParser()
    parser.add_argument(
        "-m", "--mode", choices=["user", "bot"], default="user",
        help="'user'=forward in user mode,'bot'=forward in bot mode"
    )
    parser.add_argument(
        "-R", "--restart", action=BooleanOptionalAction,
        help="The program will restart searching for new messages on origin chat."
    )
    parser.add_argument("-o", "--orig", help="Origin chat id")
    parser.add_argument("-d", "--dest", help="Destination chat id")
    parser.add_argument("-q", "--query", type=str, default="", help="Query sting")
    parser.add_argument("-r", "--resume", action=BooleanOptionalAction, help="Resume task")
    parser.add_argument("-l", "--limit", type=int, default=0, help="Max number of messages to forward")
    parser.add_argument("-f", "--filter", type=str, default=None, help="Filter messages by kind")
    parser.add_argument('-i', '--api-id', type=int, help="Api id")
    parser.add_argument('-s', '--api-hash', type=str, help="Api hash")
    parser.add_argument('-b', '--bot-token', type=str, help="Token of a bot")
    options = parser.parse_args()

    configs = {}
    chats = {}

    from_chat = options.orig
    to_chat = options.dest
    mode = options.mode
    query = options.query
    limit = options.limit
    filter = options.filter
    filter = filter.split(",") if filter else None

    if not options.orig or not options.dest:
        print("Erro: Você deve especificar os chats de origem e destino (-o e -d).")
        exit()

    if options.api_id:
        client, configs["bot_id"] = connect_to_api(options.api_id, options.api_hash, options.bot_token)
        if not os.path.exists('config.ini'):
            data = f"[default]\nbot_id:{configs['bot_id'].split(':')[1]}\nuser_delay_seconds:10\nbot_delay_seconds:5"

            with open('config.ini', 'w') as f:
                f.write(data)


    else:
        if not os.path.exists('config.ini'):
            data = "[default]\nbot_id:none\nuser_delay_seconds:10\nbot_delay_seconds:5"
            with open('config.ini', 'w') as f:
                f.write(data)
        config_data = ConfigParser()
        config_data.read("config.ini")
        config_data = dict(config_data["default"])
        configs["user_delay_seconds"] = float(config_data["user_delay_seconds"])
        configs["bot_delay_seconds"] = float(config_data["bot_delay_seconds"])
        configs["bot_id"] = config_data["bot_id"]

    delay = configs["user_delay_seconds"] if mode == "user" \
        else configs["bot_delay_seconds"]

    if options.restart:
        while True:
            get_full_chat()
            countdown()
    else:
        get_full_chat()