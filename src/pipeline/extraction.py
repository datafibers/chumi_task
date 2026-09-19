import os
import json
from openai import OpenAI
from dotenv import load_dotenv
from src.models import ExtractionResult

load_dotenv()

# Initialize OpenAI client pointing to OpenRouter
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

def extract_signals_from_context(context_text: str) -> ExtractionResult:
    """
    Calls OpenRouter (e.g., using a gemini or open-source model) to extract structured MarketSignals.
    """
    prompt = f"""
    You are an expert market intelligence AI. 
    Analyze the following chat context and extract structured market signals for AI resources (API quotas, accounts, compute).
    
    Context:
    {context_text}
    """
    
    try:
        response = client.chat.completions.create(
            model="google/gemini-2.5-flash", # Or any other model supported by OpenRouter
            messages=[
                {"role": "user", "content": prompt}
            ],
            # Use structured output feature if the model supports it, 
            # otherwise prompt the model to return JSON matching the schema.
            response_format={"type": "json_object"},
            extra_headers={
                "HTTP-Referer": "https://chumi-task.local", # Required by OpenRouter
                "X-Title": "Market Signal Bot",
            }
        )
        
        # In a real scenario, we'd use instructor or carefully parse this.
        # Here we ask for JSON and parse it into our Pydantic model.
        content = response.choices[0].message.content
        # In this basic version, ensure the prompt explicitly asks for {"signals": [...]}
        data = json.loads(content)
        return ExtractionResult(**data)
        
    except Exception as e:
        print(f"Error during extraction: {e}")
        return ExtractionResult(signals=[])
