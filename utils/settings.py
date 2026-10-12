import os
import json
import logging

from utils.file_creator import create_default_configs, AI_MODELS_CONFIG

logger = logging.getLogger(__name__)

def load_ai_models(type="list"):
    """
    Load AI model configuration.

    Args:
        type (str): return format
            - "list": return a flat list of all models [model1, model2, ...]
            - "dict"/"json": return the raw config format {provider: [model1, model2, ...]}

    Returns:
        Model configuration in the format specified by the type argument.
    """
    try:
        models_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'ai_models.json')

        # If the config file doesn't exist, create the default config
        if not os.path.exists(models_path):
            create_default_configs()

        # Read the JSON config file
        with open(models_path, 'r', encoding='utf-8') as f:
            models_config = json.load(f)

            # Return different formats based on the type argument
            if type.lower() in ["dict", "json"]:
                return models_config

            # Default: return a flat model list
            all_models = []
            for provider, models in models_config.items():
                all_models.extend(models)

            # Ensure the list is not empty
            if all_models:
                return all_models

    except (FileNotFoundError, IOError, json.JSONDecodeError) as e:
        logger.error(f"Failed to load AI model config: {e}")

    # If anything went wrong, return a default value based on type
    if type.lower() in ["dict", "json"]:
        return AI_MODELS_CONFIG

    # Default: return a flat model list
    return ["gpt-3.5-turbo", "gemini-1.5-flash", "claude-3-sonnet"]

def load_summary_times():
    """Load the list of summary times."""
    try:
        times_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'summary_times.txt')
        if not os.path.exists(times_path):
            create_default_configs()

        with open(times_path, 'r', encoding='utf-8') as f:
            times = [line.strip() for line in f if line.strip()]
            if times:
                return times
    except (FileNotFoundError, IOError) as e:
        logger.warning(f"Failed to load summary_times.txt: {e}, using default time list")
    return ['00:00', '06:00', '12:00', '18:00']

def load_delay_times():
    """Load the list of delay times."""
    try:
        times_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'delay_times.txt')
        if not os.path.exists(times_path):
            create_default_configs()

        with open(times_path, 'r', encoding='utf-8') as f:
            times = [line.strip() for line in f if line.strip()]
            if times:
                return times
    except (FileNotFoundError, IOError) as e:
        logger.warning(f"Failed to load delay_times.txt: {e}, using default time list")
    return [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

def load_max_media_size():
    """Load the media size limit."""
    try:
        size_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'max_media_size.txt')
        if not os.path.exists(size_path):
            create_default_configs()

        with open(size_path, 'r', encoding='utf-8') as f:
            size = [line.strip() for line in f if line.strip()]
            if size:
                return size

    except (FileNotFoundError, IOError) as e:
        logger.warning(f"Failed to load max_media_size.txt: {e}, using default size limit")
    return [5,10,15,20,50,100,200,300,500,1024,2048]


def load_media_extensions():
    """Load the list of media extensions."""
    try:
        size_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'media_extensions.txt')
        if not os.path.exists(size_path):
            create_default_configs()

        with open(size_path, 'r', encoding='utf-8') as f:
            size = [line.strip() for line in f if line.strip()]
            if size:
                return size

    except (FileNotFoundError, IOError) as e:
        logger.warning(f"Failed to load media_extensions.txt: {e}, using default extensions")
    return ['no extension','txt','jpg','png','gif','mp4','mp3','wav','ogg','flac','aac','wma','m4a','m4v','mov','avi','mkv','webm','mpg','mpeg','mpe','mp3','mp2','m4a','m4p','m4b','m4r','m4v','mpg','mpeg','mp2','mp3','mp4','mpc','oga','ogg','wav','wma','3gp','3g2','3gpp','3gpp2','amr','awb','caf','flac','m4a','m4b','m4p','oga','ogg','opus','spx','vorbis','wav','wma','webm','aac','ac3','dts','dtshd','flac','mp3','mp4','m4a','m4b','m4p','oga','ogg','wav','wma','webm','aac','ac3','dts','dtshd','flac','mp3','mp4','m4a','m4b','m4p','oga','ogg','wav','wma','webm']
