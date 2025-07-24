from google import genai

client = genai.Client(api_key="AIzaSyC0WodnG1Fyf583lXdtZU6kCdU1k1BTdzg")

response = client.models.generate_content(
    model="gemini-2.5-flash", contents="Explain how AI works in a few words"
)
print(response.text)