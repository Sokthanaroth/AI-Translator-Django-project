"""
AI Translator Telegram Bot (cleaned)

This file provides a lightweight, standalone Telegram bot that:
- Handles text commands and messages
- Receives voice messages, converts them to WAV via ffmpeg, and transcribes using SpeechRecognition
- Provides a /diag command to report environment diagnostics
- Sends plain-text replies (no Markdown) to avoid Telegram entity parsing errors

Notes:
- Ensure SpeechRecognition and imageio-ffmpeg are installed in the Python environment running this script.
- Ensure ffmpeg executable path is correct for your system or install ffmpeg on PATH.
"""

import logging
import os
import sys
import tempfile
import traceback
from pathlib import Path

from telegram import ReplyKeyboardMarkup, KeyboardButton, Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration - replace with your token or load from env
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "REPLACE_WITH_YOUR_TOKEN")

import shutil


def get_ffmpeg_exe():
    # 1. Check system PATH
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg and os.path.exists(system_ffmpeg):
        return system_ffmpeg

    # 2. Common Windows install path
    common_windows_path = r"C:\ffmpeg\bin\ffmpeg.exe"
    if os.path.exists(common_windows_path):
        return common_windows_path

    # 3. imageio_ffmpeg fallback
    try:
        from imageio_ffmpeg import get_ffmpeg_exe as imageio_ffmpeg_path
        candidate = imageio_ffmpeg_path()
        if candidate and os.path.exists(candidate):
            return candidate
    except Exception as e:
        logger.warning(f"imageio_ffmpeg error: {e}")

    return None


FFMPEG_EXE = get_ffmpeg_exe()
if not FFMPEG_EXE:
    logger.error("FFmpeg not found!")
else:
    logger.info(f"Using ffmpeg executable: {FFMPEG_EXE}")

# Keyboards
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🌐 Translate"), KeyboardButton("✏️ Fix Grammar")],
        [KeyboardButton("📝 Improve Writing"), KeyboardButton("🎭 Tone Adjustment")],
        [KeyboardButton("ℹ️ Help")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "translate"
    welcome = (
        "Welcome to AI Translator Bot!\n\n"
        "I can help you with:\n"
        "- Translate — English ↔ Khmer (auto-detect)\n"
        "- Fix Grammar (English)\n"
        "- Improve Writing (English)\n"
        "- Tone Adjustment (English)\n\n"
        "Send text, files, images, or voice messages to process."
    )
    await update.message.reply_text(welcome, reply_markup=MAIN_KEYBOARD, parse_mode=None)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Help:\n"
        "- Send text to translate or process.\n"
        "- Send a voice message to transcribe.\n"
        "- Use /diag to get environment diagnostics."
    )
    await update.message.reply_text(help_text, parse_mode=None)


async def diag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return diagnostics about the Python environment and module availability."""
    try:
        python_exe = sys.executable
        site_packages = [p for p in sys.path if 'site-packages' in str(p)][:5]
        spec_sr = None
        try:
            import importlib.util

            spec_sr = importlib.util.find_spec("speech_recognition")
        except Exception:
            spec_sr = None

        msg_lines = [
            f"Python executable: {python_exe}",
            f"Top sys.path entries: {sys.path[:6]}",
            f"speech_recognition available: {spec_sr is not None}",
            f"ffmpeg executable: {FFMPEG_EXE}",
        ]
        await update.message.reply_text("\n".join(msg_lines), parse_mode=None)
    except Exception as e:
        await update.message.reply_text(f"Error collecting diagnostics: {str(e)}", parse_mode=None)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    # Simple echo/placeholder behavior — integrate your existing processing here
    await update.message.reply_text(f"You said: {text}", parse_mode=None)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Download voice message, convert to WAV, and transcribe using SpeechRecognition.

    This handler gracefully handles missing SpeechRecognition and ffmpeg.
    """
    voice = update.message.voice
    if voice is None:
        await update.message.reply_text("No voice attachment found.", parse_mode=None)
        return

    # Check SpeechRecognition availability
    try:
        import speech_recognition as sr
    except Exception as e:
        logger.exception("SpeechRecognition not available")
        await update.message.reply_text(
            "SpeechRecognition package is not installed in this Python environment.\n"
            "Install with: python -m pip install --user SpeechRecognition imageio-ffmpeg"
        , parse_mode=None)
        return

    # Download file to temp
    file = await update.message.voice.get_file()
    with tempfile.TemporaryDirectory() as tmpdir:
        ogg_path = Path(tmpdir) / "voice.ogg"
        wav_path = Path(tmpdir) / "voice.wav"
        await file.download_to_drive(str(ogg_path))

        # Convert to WAV using ffmpeg
        if not FFMPEG_EXE or not os.path.exists(FFMPEG_EXE):
            await update.message.reply_text(
                "FFmpeg is not installed or not found.", parse_mode=None
            )
            return
        try:
            from subprocess import run, PIPE

            cmd = [FFMPEG_EXE, "-y", "-i", str(ogg_path), "-ar", "16000", str(wav_path)]
            logger.info(f"Running ffmpeg: {' '.join(cmd)}")
            proc = run(cmd, stdout=PIPE, stderr=PIPE, check=False)
            if proc.returncode != 0 or not wav_path.exists():
                logger.error("ffmpeg failed: %s", proc.stderr.decode(errors='replace'))
                await update.message.reply_text(
                    "Audio conversion failed. Ensure ffmpeg is installed and accessible."
                , parse_mode=None)
                return
        except FileNotFoundError as e:
            logger.exception("FFmpeg file not found")
            await update.message.reply_text(
                f"FFmpeg not found.\n\nDetails:\n{str(e)}", parse_mode=None
            )
            return
        except Exception:
            logger.exception("Error running ffmpeg")
            await update.message.reply_text("Audio conversion error.", parse_mode=None)
            return

        # Transcribe WAV
        recognizer = sr.Recognizer()
        try:
            with sr.AudioFile(str(wav_path)) as source:
                audio_data = recognizer.record(source)
            # Try Khmer first, then fallback to English
            text = None
            try:
                text = recognizer.recognize_google(audio_data, language='km-KH')
            except Exception:
                try:
                    text = recognizer.recognize_google(audio_data, language='en-US')
                except Exception as ex:
                    logger.exception("Transcription failed: %s", ex)
                    await update.message.reply_text("Transcription failed: couldn't recognize speech.", parse_mode=None)
                    return

            await update.message.reply_text(f"Transcription:\n{text}", parse_mode=None)
        except Exception:
            logger.exception("Error during transcription")
            await update.message.reply_text("An error occurred during transcription.", parse_mode=None)


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle general audio attachments (`audio` messages)."""
    audio = update.message.audio
    if audio is None:
        await update.message.reply_text("No audio attachment found.", parse_mode=None)
        return

    try:
        file = await update.message.audio.get_file()
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_name = audio.file_name or "audio.ogg"
            in_path = Path(tmpdir) / orig_name
            out_wav = Path(tmpdir) / "audio.wav"
            await file.download_to_drive(str(in_path))

            if not FFMPEG_EXE or not os.path.exists(FFMPEG_EXE):
                await update.message.reply_text(
                    "FFmpeg is not installed or not found.", parse_mode=None
                )
                return
            try:
                from subprocess import run, PIPE

                cmd = [FFMPEG_EXE, "-y", "-i", str(in_path), "-ar", "16000", str(out_wav)]
                logger.info(f"Running ffmpeg: {' '.join(cmd)}")
                proc = run(cmd, stdout=PIPE, stderr=PIPE, check=False)
                if proc.returncode != 0 or not out_wav.exists():
                    logger.error("ffmpeg failed: %s", proc.stderr.decode(errors='replace'))
                    await update.message.reply_text("Audio conversion failed.", parse_mode=None)
                    return
            except FileNotFoundError as e:
                logger.exception("FFmpeg file not found")
                await update.message.reply_text(
                    f"FFmpeg not found.\n\nDetails:\n{str(e)}", parse_mode=None
                )
                return
            except Exception:
                logger.exception("Error running ffmpeg")
                await update.message.reply_text("Audio conversion error.", parse_mode=None)
                return

            try:
                import speech_recognition as sr
            except Exception:
                await update.message.reply_text(
                    "SpeechRecognition not installed. Install with: python -m pip install --user SpeechRecognition imageio-ffmpeg",
                    parse_mode=None,
                )
                return

            recognizer = sr.Recognizer()
            try:
                with sr.AudioFile(str(out_wav)) as source:
                    audio_data = recognizer.record(source)
                text = None
                try:
                    text = recognizer.recognize_google(audio_data, language='km-KH')
                except Exception:
                    try:
                        text = recognizer.recognize_google(audio_data, language='en-US')
                    except Exception:
                        await update.message.reply_text("Transcription failed: couldn't recognize speech.", parse_mode=None)
                        return

                await update.message.reply_text(f"Transcription:\n{text}", parse_mode=None)
            except Exception:
                logger.exception("Error during transcription of audio file")
                await update.message.reply_text("An error occurred during transcription.", parse_mode=None)
    except Exception:
        logger.exception("Error handling audio attachment")
        await update.message.reply_text("Error handling audio file.", parse_mode=None)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document uploads (pdf, docx, txt, etc.) by saving them to `uploads/` and acknowledging."""
    doc = update.message.document
    if doc is None:
        await update.message.reply_text("No document found in the message.", parse_mode=None)
        return

    uploads_dir = Path.cwd() / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    try:
        file = await doc.get_file()
        dest = uploads_dir / (doc.file_name or f"doc_{doc.file_id}")
        await file.download_to_drive(str(dest))
        await update.message.reply_text(f"Saved document: {dest.name} ({round(doc.file_size/1024,1)} KB)", parse_mode=None)
    except Exception:
        logger.exception("Error saving document")
        await update.message.reply_text("Failed to save document.", parse_mode=None)


def main():
    if TELEGRAM_BOT_TOKEN == "REPLACE_WITH_YOUR_TOKEN":
        logger.error("Please set the TELEGRAM_BOT_TOKEN environment variable or update the script.")
        print("Please set TELEGRAM_BOT_TOKEN environment variable or update the script.")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("diag", diag_command))

    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Starting bot polling...")
    app.run_polling()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Unhandled exception in main")
