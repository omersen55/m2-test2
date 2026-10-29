"""
Yerel Ollama LLM bağlantı testi.

Kullanım:
    python llm_test.py
"""
import requests

OLLAMA_URL = "http://localhost:11434"
MODEL = "gemma2:2b"   # ollama pull gemma2:2b  (ya da qwen2.5:0.5b)


def llm_sor(soru: str, model: str = MODEL) -> str:
    """Ollama'ya soru gönderir, cevabı string olarak döndürür."""
    r = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": model, "prompt": soru, "stream": False},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["response"].strip()


def mevcut_modeller() -> list[str]:
    r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
    return [m["name"] for m in r.json().get("models", [])]


if __name__ == "__main__":
    print("Kurulu modeller:", mevcut_modeller())

    # Basit test
    cevap = llm_sor("Merhaba, kendini tek cümleyle tanıt.")
    print("Cevap:", cevap)

    # Şık seçimi testi
    test_soru = """
Aşağıdaki şıklardan hangisi bir matematik işlemidir?
Şıklar: Judo | Helsinki | 17+12 | Simpsons
Sadece doğru şıkkı yaz, başka bir şey yazma.
""".strip()
    print("\nTest sorusu:", test_soru)
    print("LLM cevabı:", llm_sor(test_soru))
