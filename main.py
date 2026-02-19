from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import boto3
import os
import logging
from datetime import datetime, timedelta

# Configuração de logging
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
    return {"mensagem": "API Controle Hidrico Online - Debug de urineType"}

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
        logger.info(f"Registros brutos encontrados: {len(items)}")
        
        # Converter Decimal para float
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
        return None
    
    campo_data = 'timestamp'
    campo_liquido = 'quantidadeLiquidoMl'
    
    # FILTRAGEM: Manter apenas registros que possuem o campo de data
    regs_validos = [r for r in registros if campo_data in r and r[campo_data]]
    
    if not regs_validos:
        return None

    # Ordenação cronológica
    regs = sorted(regs_validos, key=lambda x: x[campo_data])

    # DEBUG: Inspecionar os valores de urineType nos registros
    urine_types_encontrados = set()
    exemplo_urina = None
    for r in regs:
        u_type = r.get('urineType')
        if u_type is not None:
            urine_types_encontrados.add(f"{u_type} ({type(u_type).__name__})")
            if u_type == 1 or str(u_type) == "1":
                exemplo_urina = r
    
    logger.info(f"Valores de 'urineType' encontrados no histórico: {list(urine_types_encontrados)}")
    if not exemplo_urina:
        # Se não achou 1, vamos ver o que tem em um registro que parece ser de urina
        for r in regs:
            if 'quantidadeUrinaMl' in r:
                logger.info(f"Exemplo de registro de urina: {r}")
                break

    # Identificar cateterismos (urineType = 1 ou "1")
    cateterismos = [i for i, r in enumerate(regs) if str(r.get('urineType')) == "1"]
    logger.info(f"Índices de cateterismo encontrados: {cateterismos}")
    
    if len(cateterismos) < 2:
        logger.warning(f"Dados insuficientes: {len(cateterismos)} cateterismos encontrados.")
        return None

    # Calcular volumes entre cateterismos
    intervalos_vol = []
    for i in range(len(cateterismos) - 1):
        idx_start, idx_end = cateterismos[i], cateterismos[i+1]
        vol = sum(float(regs[j].get(campo_liquido, 0) or 0) for j in range(idx_start, idx_end))
        intervalos_vol.append(vol)

    media_vol = sum(intervalos_vol) / len(intervalos_vol)
    idx_last_cat = cateterismos[-1]
    vol_desde_ultimo = sum(float(regs[j].get(campo_liquido, 0) or 0) for j in range(idx_last_cat, len(regs)))
    restante = media_vol - vol_desde_ultimo
    
    try:
        def parse_date(date_str):
            try:
                if isinstance(date_str, (int, float)):
                    return datetime.fromtimestamp(date_str)
                return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            except:
                if isinstance(date_str, (int, float)) and date_str > 1e11:
                    return datetime.fromtimestamp(date_str / 1000)
                raise

        t_last_cat = parse_date(regs[idx_last_cat][campo_data])
        t_first_cat = parse_date(regs[cateterismos[0]][campo_data])
        
        total_sec = (t_last_cat - t_first_cat).total_seconds()
        num_intervalos = len(cateterismos) - 1
        
        if total_sec <= 0:
            return {"previsao": "Erro de cronologia", "liquido_restante_ml": restante}
        
        taxa_ml_sec = media_vol / (total_sec / num_intervalos)
        if taxa_ml_sec <= 0:
            return {"previsao": "Taxa zero", "liquido_restante_ml": restante}
        
        sec_restante = restante / taxa_ml_sec
        previsao_hora = t_last_cat + timedelta(seconds=sec_restante)
        
        return {
            "tempo_restante_aprox": str(timedelta(seconds=int(max(0, sec_restante)))),
            "proximo_horario_previsto": previsao_hora.isoformat(),
            "liquido_restante_ml": round(restante, 2),
            "media_historica_ml": round(media_vol, 2),
            "debug": {
                "cateterismos": len(cateterismos),
                "urine_types": list(urine_types_encontrados)
            }
        }
    except Exception as e:
        logger.error(f"Erro cálculo: {str(e)}")
        return None

@app.get("/prever-cateterismo/{user_id}")
def prever(user_id: str):
    regs = buscar_historico(user_id)
    if not regs:
        raise HTTPException(status_code=404, detail="Usuário sem registros.")
    res = calcular_previsao(regs)
    if not res:
        raise HTTPException(status_code=400, detail="Dados insuficientes (cateterismos não encontrados). Verifique os logs para ver os valores de urineType.")
    return res
