from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from mangum import Mangum
import boto3
import os
from datetime import datetime, timedelta

app = FastAPI()

# Inicialização global do DynamoDB
dynamodb = boto3.resource(
    "dynamodb",
    region_name=os.environ.get("AWS_REGION", "us-east-1")
)
table_registros = dynamodb.Table("controleHidrico")

@app.get("/healthcheck")
def healthcheck():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.get("/")
def raiz():
    return {"mensagem": "API Controle Hidrico Online"}

def buscar_historico(user_id: str, limit: int = 200):
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

def calcular_previsao(registros: List[dict]):
    if not registros: return None
    
    try:
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
    
    # Ingestão desde o último
    idx_last = cateterismos[-1]
    vol_desde_last = sum(float(regs[j].get('quantidadeLiquidoM', 0) or 0) for j in range(idx_last, len(regs)))
    
    restante = media_vol - vol_desde_last
    
    # Cálculo de tempo simplificado
    t_last = datetime.fromisoformat(regs[idx_last]['horario'].replace('Z', '+00:00'))
    t_first_cat = datetime.fromisoformat(regs[cateterismos[0]]['horario'].replace('Z', '+00:00'))
    total_sec = (t_last - t_first_cat).total_seconds()
    
    if total_sec <= 0: return {"previsao": "Dados insuficientes", "liquido_restante_ml": restante}
    
    taxa = media_vol / (total_sec / (len(cateterismos) - 1)) if len(cateterismos) > 1 else 0
    
    if taxa <= 0: return {"previsao": "Aguardando mais dados", "liquido_restante_ml": restante}
    
    sec_restante = restante / (taxa / 3600) # ml por hora
    previsao_hora = t_last + timedelta(seconds=sec_restante)

    return {
        "tempo_restante_aprox": str(timedelta(seconds=sec_restante)),
        "proximo_horario": previsao_hora.isoformat(),
        "liquido_restante_ml": round(restante, 2),
        "media_historica_ml": round(media_vol, 2)
    }

@app.get("/prever-cateterismo/{user_id}")
def prever(user_id: str):
    regs = buscar_historico(user_id)
    if not regs: raise HTTPException(status_code=404, detail="Sem registros")
    res = calcular_previsao(regs)
    if not res: raise HTTPException(status_code=400, detail="Dados insuficientes")
    return res

handler = Mangum(app)
