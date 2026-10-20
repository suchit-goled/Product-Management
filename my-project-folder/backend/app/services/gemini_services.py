from google import genai
from config import Config

client = genai.Client(api_key=Config.GEMINI_API_KEY)