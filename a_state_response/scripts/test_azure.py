"""Quick connection test: one tiny call to each endpoint form. Uses AZURE_OPENAI_API_KEY and AZURE_DEPLOYMENT."""
import os
from openai import OpenAI
base = os.environ["AZURE_OPENAI_ENDPOINT"].split(".openai.azure.com")[0].split(".services.ai.azure.com")[0]
for ep in (base + ".openai.azure.com/openai/v1/", base + ".services.ai.azure.com/openai/v1/"):
    try:
        c = OpenAI(base_url=ep, api_key=os.environ["AZURE_OPENAI_API_KEY"])
        r = c.chat.completions.create(model=os.environ["AZURE_DEPLOYMENT"], messages=[{"role": "user", "content": "Reply with OK"}],
                                      max_completion_tokens=200, reasoning_effort="minimal")
        print("WORKS  ", ep, "->", r.choices[0].message.content, "| model:", r.model)
    except Exception as e:
        print("FAILS  ", ep, "->", str(e)[:200])
