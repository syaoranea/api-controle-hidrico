from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import boto3
import os
import logging
from datetime import datetime, timedelta

# Configuração de logging para aparecer no console da Vercel
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api-controle-hidrico")

app = FastAPI()

# Inicialização do DynamoDB
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
    return {"mensagem": "API Controle Hidrico Online com Logs Detalhados"}

def buscar_historico(user_id: str, limit: int = 200):
    logger.info(f"Buscando histórico para o usuário: {user_id}")
    try:
        response = table_registros.query(
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": f"USER#{user_id}"},
            Limit=limit,
            ScanIndexForward=False
        )
        items = response.get("Items", [])
        logger.info(f"Registros encontrados no DynamoDB: {len(items)}")
        
        for item in items:
            for key, value in item.items():
                if hasattr(value, 'to_eng_string'):
                    item[key] = float(value)
        return items
    except Exception as e:
        logger.error(f"Erro ao acessar DynamoDB: {str(e)}")
        return []

def calcular_previsao(registros: List[dict]):
    if not registros:
        logger.warning("Nenhum registro fornecido para o cálculo.")
        return None
    
    try:
        # Ordenação cronológica (do mais antigo para o mais novo)
        regs = sorted(registros, key=lambda x: x['horario'])
        logger.info(f"Registros ordenados cronologicamente. Primeiro: {regs[0]['horario']}, Último: {regs[-1]['horario']}")
    except Exception as e:
        logger.error(f"Erro ao ordenar registros: {str(e)}")
        return None

    # Identificar cateterismos (urineType = 1)
    cateterismos = [i for i, r in enumerate(regs) if r.get('urineType') == 1]
    logger.info(f"Índices de cateterismo (urineType=1) encontrados: {cateterismos}")
    
    if len(cateterismos) < 2:
        logger.warning(f"Cateterismos insuficientes para média. Encontrados: {len(cateterismos)}")
        return None

    # Calcular volumes entre cateterismos
    intervalos_vol = []
    for i in range(len(cateterismos) - 1):
        idx_start, idx_end = cateterismos[i], cateterismos[i+1]
        vol = sum(float(regs[j].get('quantidadeLiquidoM', 0) or 0) for j in range(idx_start, idx_end))
        intervalos_vol.append(vol)
        logger.info(f"Intervalo {i}: Volume ingerido entre cateterismo {i} e {i+1} = {vol}ml")

    media_vol = sum(intervalos_vol) / len(intervalos_vol)
    logger.info(f"Média histórica de ingestão entre cateterismos: {media_vol}ml")
    
    # Calcular ingestão desde o último cateterismo até o momento atual (último registro)
    idx_last_cat = cateterismos[-1]
    vol_desde_ultimo = sum(float(regs[j].get('quantidadeLiquidoM', 0) or 0) for j in range(idx_last_cat, len(regs)))
    logger.info(f"Volume ingerido desde o último cateterismo: {vol_desde_ultimo}ml")
    
    restante = media_vol - vol_desde_ultimo
    logger.info(f"Volume restante estimado para o próximo cateterismo: {restante}ml")
    
    try:
        # Cálculo de tempo baseado na taxa histórica
        t_last_cat = datetime.fromisoformat(regs[idx_last_cat]['horario'].replace('Z', '+00:00'))
        t_first_cat = datetime.fromisoformat(regs[cateterismos[0]]['horario'].replace('Z', '+00:00'))
        
        # Tempo total decorrido entre o primeiro e o último cateterismo do histórico
        total_sec_historico = (t_last_cat - t_first_cat).total_seconds()
        num_intervalos = len(cateterismos) - 1
        
        if total_sec_historico <= 0:
            logger.error("Tempo total de histórico inválido (zero ou negativo).")
            return {"previsao": "Erro no histórico de tempo", "liquido_restante_ml": restante}
        
        # Média de segundos por intervalo
        avg_sec_per_interval = total_sec_historico / num_intervalos
        
        # Taxa de ingestão (ml por segundo)
        taxa_ml_sec = media_vol / avg_sec_per_interval
        logger.info(f"Taxa de ingestão calculada: {taxa_ml_sec} ml/s ({taxa_ml_sec * 3600} ml/h)")
        
        if taxa_ml_sec <= 0:
            logger.warning("Taxa de ingestão é zero ou negativa.")
            return {"previsao": "Taxa de ingestão não calculável", "liquido_restante_ml": restante}
        
        # Tempo restante em segundos
        sec_restante = restante / taxa_ml_sec
        previsao_hora = t_last_cat + timedelta(seconds=sec_restante)
        
        logger.info(f"Previsão calculada: {previsao_hora.isoformat()} (em {sec_restante} segundos)")

        return {
            "tempo_restante_aprox": str(timedelta(seconds=int(max(0, sec_restante)))),
            "proximo_horario_previsto": previsao_hora.isoformat(),
            "liquido_restante_ml": round(restante, 2),
            "media_historica_ml": round(media_vol, 2),
            "taxa_ml_hora": round(taxa_ml_sec * 3600, 2),
            "debug": {
                "total_registros": len(regs),
                "num_cateterismos": len(cateterismos),
                "vol_desde_ultimo": vol_desde_ultimo
            }
        }
    except Exception as e:
        logger.error(f"Erro durante o cálculo de tempo: {str(e)}")
        return None

@app.get("/prever-cateterismo/{user_id}")
def prever(user_id: str):
    logger.info(f"--- Início da requisição para user_id: {user_id} ---")
    regs = buscar_historico(user_id)
    
    if not regs:
        logger.warning(f"Nenhum registro encontrado para o usuário {user_id}")
        raise HTTPException(status_code=404, detail="Sem registros no DynamoDB para este usuário.")
    
    res = calcular_previsao(regs)
    
    if not res:
        logger.warning("Cálculo de previsão retornou None (dados insuficientes).")
        raise HTTPException(status_code=400, detail="Dados insuficientes para cálculo (necessário pelo menos 2 cateterismos no histórico).")
    
    logger.info(f"Requisição finalizada com sucesso para {user_id}")
    return res
