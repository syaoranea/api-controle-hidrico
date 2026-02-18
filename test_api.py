import requests
import time
import subprocess
import os

def test_api():
    # Iniciar o servidor em segundo plano
    process = subprocess.Popen(
        ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd="/home/ubuntu/python_api_project",
        stdout=subprocess.PIPE,  # Capturar a saída padrão
        stderr=subprocess.PIPE   # Capturar a saída de erro
    )
    time.sleep(5)  # Esperar o servidor iniciar

    base_url = "http://127.0.0.1:8000"
    
    try:
        # 1. Testar Raiz
        print("Testando GET /...")
        r = requests.get(f"{base_url}/")
        assert r.status_code == 200
        print("OK!")

        # 2. Testar Healthcheck
        print("Testando GET /healthcheck...")
        r = requests.get(f"{base_url}/healthcheck")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        print("OK!")

        print("\nTodos os testes básicos passaram com sucesso!")

    finally:
        process.terminate()
        # Opcional: imprimir a saída do servidor para depuração
        # stdout, stderr = process.communicate()
        # print("\nServer STDOUT:", stdout.decode())
        # print("Server STDERR:", stderr.decode())

if __name__ == "__main__":
    test_api()
