import logging
from queue import Queue
import pickle

from botBase import pi_bot

import openai
from telegram import (
    Update,
    Message,
)
from telegram.constants import ParseMode
from telegram.ext import (
    filters,
    MessageHandler,
    ContextTypes,
    CommandHandler,
    Application,
)

LOG_FILE = "WitiBotFiles/bot.log"
BOT_TOKEN_FILE = "WitiBotFiles/TOKEN.token"
OPENAI_TOKEN_FILE = "WitiBotFiles/OPENAI.token"
MESSAGES_FILE = "WitiBotFiles/message_backlog.pickle"
DEVELOPER_CHAT_ID = 631157495
MESSAGE_BACKLOG = {}
BACKLOG_LENGTH = 200
APPROVED_CHATS = [631157495, -1001517711069]
PRINT_LIMIT = 10


def update_messages_pickle():
    global MESSAGE_BACKLOG
    modified_message_backlog = {
        user: list(messages.queue) for user, messages in MESSAGE_BACKLOG.items()
    }
    with open(MESSAGES_FILE) as f:
        pickle.dump(modified_message_backlog, f)


def load_messages_pickle(queue_size=100):
    global MESSAGE_BACKLOG
    try:
        with open(MESSAGES_FILE, "rb") as f:
            modified_message_backlog = pickle.load(f)
        MESSAGE_BACKLOG = {
            user: Queue(maxsize=queue_size) for user in modified_message_backlog
        }
        [
            MESSAGE_BACKLOG[user].put(message)
            for user, messages in modified_message_backlog.items()
            for _, message in zip(range(queue_size), messages)
        ]
    except (FileNotFoundError, EOFError):
        pass


async def post_init(application: Application) -> None:
    load_messages_pickle()
    await application.bot.send_message(
        chat_id=DEVELOPER_CHAT_ID,
        text="Bot started!",
    )
    logging.info("Loaded message backlog")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MESSAGE_BACKLOG

    if (
        update.effective_chat.id not in APPROVED_CHATS
        and update.effective_user.id != DEVELOPER_CHAT_ID
    ):
        return

    if update.effective_chat.id in MESSAGE_BACKLOG:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="I'm already listening to this chat."
        )
        return

    backlog_length = BACKLOG_LENGTH
    if context.args:
        backlog_length = int(context.args[0])

    MESSAGE_BACKLOG[update.effective_chat.id] = Queue(maxsize=backlog_length)
    update_messages_pickle()

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="I will now start listening to this chat. "
        + f"I will save the last {backlog_length} "
        + "messages and will summarize them to you if you ask me to.",
    )

    logging.info(
        f"Started listening to <{update.effective_chat.title}> "
        + f"with id {update.effective_chat.id} "
        + f"and backlog length {backlog_length}"
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    MESSAGE_BACKLOG.pop(update.effective_chat.id)
    update_messages_pickle()

    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="I will no longer listen to this chat."
    )

    logging.info(
        f"Stopped listening to <{update.effective_chat.title}> "
        + f"with id {update.effective_chat.id}"
    )


async def show_backlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    backlog = MESSAGE_BACKLOG[update.effective_chat.id]
    if backlog.empty():
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="I haven't seen any messages yet."
        )
    elif backlog.qsize() < PRINT_LIMIT:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Here's what I've seen so far:\n{format_backlog(backlog)}",
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Here's what I've seen so far:\n...\n{format_backlog(backlog[-PRINT_LIMIT:])}",
        )

    logging.info(
        f"Sent backlog to {update.effective_chat.title} "
        + f"with id {update.effective_chat.id}"
    )


async def log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    backlog = MESSAGE_BACKLOG[update.effective_chat.id]
    if backlog.full():
        backlog.get()

    user = (
        update.effective_message.forward_from.name
        if update.effective_message.forward_from is not None
        else update.effective_user.name
    )
    backlog.put((user, update.effective_message.text))
    update_messages_pickle()

    logging.info(
        f"Added message to backlog of {update.effective_chat.title} "
        + f"with id {update.effective_chat.id}"
    )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    MESSAGE_BACKLOG[update.effective_chat.id].queue.clear()
    update_messages_pickle()
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="Cleared backlog."
    )
    logging.info(
        f"Cleared backlog of {update.effective_chat.title}"
        + f"with id {update.effective_chat.id}"
    )


async def summarize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    response_chat_id = update.effective_user.id
    response_language = "English"

    if context.args:
        i = 0
        while i < len(context.args):
            arg = context.args[i]
            if arg == "-ingroup":
                response_chat_id = update.effective_chat.id
            elif arg == "-language":
                response_language = context.args[i + 1]
                i += 1
            i += 1

    backlog = MESSAGE_BACKLOG[update.effective_chat.id]
    logging.info(
        f"Summarizing {update.effective_chat.title}"
        + f"with id {update.effective_chat.id}"
    )

    if backlog.empty():
        await context.bot.send_message(
            chat_id=response_chat_id, text="I haven't seen any messages yet."
        )
    else:
        await context.bot.send_message(
            chat_id=response_chat_id, text="Generating summary..."
        )

        chat = [
            {
                "role": "system",
                "content": f"Summazrize the following chat conversation in {response_language}",
            },
            {"role": "user", "content": format_backlog(backlog)},
        ]

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=chat,
        )

        finish_reason = response["choices"][0]["finish_reason"]  # type: ignore
        usage = response["usage"]["total_tokens"]  # type: ignore
        summary = response["choices"][0]["message"]["content"]  # type: ignore

        logging.info(
            f"Finished summarizing with reason: {finish_reason}"
            + f" and a usage: {usage} total tokens"
        )

        if finish_reason == "stop":  # type: ignore
            await context.bot.send_message(
                chat_id=response_chat_id,
                text=f"<b>Here is the summary of the last <i>{backlog.qsize()}</i> messages in {update.effective_chat.title}:</b>\n\n"
                + f"{summary}",  # type: ignore
                parse_mode=ParseMode.HTML,
            )
        elif finish_reason == "length":  # type: ignore
            await context.bot.send_message(
                chat_id=response_chat_id,
                text="I couldn't generate a summary because the chat was too long.",
            )
        elif finish_reason == "content_filter":  # type: ignore
            await context.bot.send_message(
                chat_id=response_chat_id,
                text="I couldn't generate a summary because the chat contained sensitive content.",
            )

    await context.bot.delete_message(
        update.effective_chat.id, update.effective_message.id
    )

    logging.info(
        f"Sent summary to <{update.effective_user.name}> "
        + f"with id {update.effective_user.id}"
    )


async def prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    backlog = MESSAGE_BACKLOG[update.effective_chat.id]
    logging.info(
        f"Summarizing {update.effective_chat.title}"
        + f"with id {update.effective_chat.id}"
    )

    if context.args == []:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Please provide a prompt."
        )
    else:
        temp_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Answering prompt..."
        )

        chat = [
            {
                "role": "system",
                "content": f"You are a bot that listens to a conversation and "
                + "answers any question a user has. The converation context is:\n"
                + format_backlog(backlog),
            },
            {"role": "user", "content": (" ".join(context.args))},  # type: ignore
        ]

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=chat,
        )

        finish_reason = response["choices"][0]["finish_reason"]  # type: ignore
        usage = response["usage"]["total_tokens"]  # type: ignore
        summary = response["choices"][0]["message"]["content"]  # type: ignore

        logging.info(
            f"Finished summarizing with reason: {finish_reason}"
            + f" and a usage: {usage} total tokens"
        )

        if finish_reason == "stop":  # type: ignore
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"{summary}",  # type: ignore
                parse_mode=ParseMode.HTML,
            )
        elif finish_reason == "length":  # type: ignore
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="I couldn't generate a summary because the chat was too long.",
            )
        elif finish_reason == "content_filter":  # type: ignore
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="I couldn't generate a summary because the chat contained sensitive content.",
            )

        await context.bot.delete_message(update.effective_chat.id, temp_message.id)

    logging.info(
        f"Sent summary to <{update.effective_user.name}> "
        + f"with id {update.effective_user.id}"
    )


async def catch_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(
        f"Received message from {update.effective_chat.title} "
        + f"with id {update.effective_chat.id}, "
        + f"sent by {update.effective_user.name} "
        + f"with id {update.effective_user.id}"
    )


def format_backlog(backlog: Queue):
    return "\n".join([f"{name}: {message}" for name, message in list(backlog.queue)])


class ListeningTo(filters.MessageFilter):
    def filter(self, message: Message):
        return message.chat_id in MESSAGE_BACKLOG


listening_to_filter = ListeningTo()


if __name__ == "__main__":
    with open(BOT_TOKEN_FILE) as f:
        token = f.readlines()[0]
    with open(OPENAI_TOKEN_FILE) as f:
        openai.api_key = f.readlines()[0]

    commands = (
        "start - Start listening to a chat\n"
        "stop - Stop listening to a chat\n"
        "backlog - Show the backlog of a chat\n"
        "summarize - Summarize the backlog of a chat\n"
        "prompt - Prompt the AI to generate a response with the chat as context\n"
        "clear - Clear the backlog of a chat\n"
    )

    handlers = [
        CommandHandler("start", start),
        CommandHandler("stop", stop, filters=listening_to_filter),
        CommandHandler("backlog", show_backlog, filters=listening_to_filter),
        CommandHandler("summarize", summarize, filters=listening_to_filter),
        CommandHandler("prompt", prompt, filters=listening_to_filter),
        CommandHandler("clear", clear, filters=listening_to_filter),
        MessageHandler(filters.TEXT & ~(filters.COMMAND) & listening_to_filter, log),
        MessageHandler(filters.ALL, catch_all),
    ]

    pi_bot.start_bot("WitiBot", commands, LOG_FILE, token, post_init, handlers)
