from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import boto3
import os
from datetime import datetime, timedelta

app = FastAPI()

# Inicialização do DynamoDB
# A Vercel injeta AWS_ACCESS_KEY_ID e AWS_SECRET_ACCESS_KEY automaticamente se configuradas
dynamodb = boto3.resource(
    "dynamodb",
    region_name=os.environ.get("AWS_REGION", "us-east-1")
)
table_registros = dynamodb.Table("controleHidrico")

@app.get("/healthcheck")
def healthcheck():
    return {
        "status": "ok", 
        "timestamp": datetime.utcnow().isoformat(),
        "env": {
            "region": os.environ.get("AWS_REGION"),
            "has_key": bool(os.environ.get("AWS_ACCESS_KEY_ID"))
        }
    }

@app.get("/")
def raiz():
    return {"mensagem": "API Controle Hidrico Online na Raiz"}

def buscar_historico(user_id: str, limit: int = 200):
    try:
        response = table_registros.query(
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": f"USER#{user_id}"},
            Limit=limit,
            ScanIndexForward=False
        )
        items = response.get("Items", [])
        for item in items:
            for key, value in item.items():
                if hasattr(value, 'to_eng_string'):
                    item[key] = float(value)
        return items
    except Exception as e:
        print(f"Erro DynamoDB: {e}")
        return []

def calcular_previsao(registros: List[dict]):
    if not registros: return None
    
    try:
        # Garante ordenação cronológica
        regs = sorted(registros, key=lambda x: x['horario'])
    except:
        return None

    cateterismos = [i for i, r in enumerate(regs) if r.get('urineType') == 1]
    if len(cateterismos) < 2: return None

    intervalos = []
    for i in range(len(cateterismos) - 1):
        idx_start, idx_end = cateterismos[i], cateterismos[i+1]
        vol = sum(float(regs[j].get('quantidadeLiquidoM', 0) or 0) for j in range(idx_start, idx_end))
        intervalos.append(vol)

    media_vol = sum(intervalos) / len(intervalos)
    
    idx_last = cateterismos[-1]
    vol_desde_last = sum(float(regs[j].get('quantidadeLiquidoM', 0) or 0) for j in range(idx_last, len(regs)))
    
    restante = media_vol - vol_desde_last
    
    try:
        t_last = datetime.fromisoformat(regs[idx_last]['horario'].replace('Z', '+00:00'))
        t_first_cat = datetime.fromisoformat(regs[cateterismos[0]]['horario'].replace('Z', '+00:00'))
        total_sec = (t_last - t_first_cat).total_seconds()
        
        if total_sec <= 0: return {"previsao": "Dados insuficientes", "liquido_restante_ml": restante}
        
        # Média de tempo entre cateterismos
        avg_sec_between = total_sec / (len(cateterismos) - 1)
        
        # Taxa de ingestão (ml por segundo)
        taxa = media_vol / avg_sec_between
        
        if taxa <= 0: return {"previsao": "Aguardando mais dados", "liquido_restante_ml": restante}
        
        sec_restante = restante / taxa
        previsao_hora = t_last + timedelta(seconds=sec_restante)

        return {
            "tempo_restante_aprox": str(timedelta(seconds=int(sec_restante))),
            "proximo_horario": previsao_hora.isoformat(),
            "liquido_restante_ml": round(restante, 2),
            "media_historica_ml": round(media_vol, 2)
        }
    except Exception as e:
        print(f"Erro cálculo: {e}")
        return None

@app.get("/prever-cateterismo/{user_id}")
def prever(user_id: str):
    regs = buscar_historico(user_id)
    if not regs: raise HTTPException(status_code=404, detail="Sem registros no DynamoDB")
    res = calcular_previsao(regs)
    if not res: raise HTTPException(status_code=400, detail="Dados insuficientes para cálculo")
    return res
