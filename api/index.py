from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from uuid import uuid4, UUID
import pandas as pd
from mangum import Mangum
import boto3
import os
import logging
from datetime import datetime, timedelta, timezone

# Configuração de logging para ver erros no console da Vercel
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="API de Controle Hídrico",
    description="API para gerenciar o controle hídrico e prever cateterismo.",
    version="1.0.0"
)

# Inicialização do DynamoDB com tratamento de erro
try:
    dynamodb = boto3.resource(
        "dynamodb",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY")
    )
    table_registros = dynamodb.Table("controleHidrico")
    table_parametros = dynamodb.Table("tb_parametros_paciente")
    table_usuarios = dynamodb.Table("tb_usuarios_controle_hidrico")
    logger.info("Conexão com DynamoDB configurada.")
except Exception as e:
    logger.error(f"Erro ao configurar DynamoDB: {str(e)}")
    # Não levantamos erro aqui para permitir que o app inicie e mostre erros nos endpoints

@app.get("/healthcheck", tags=["Geral"])
async def healthcheck():
    # Verifica se as variáveis de ambiente estão presentes
    aws_configured = all([
        os.environ.get("AWS_ACCESS_KEY_ID"),
        os.environ.get("AWS_SECRET_ACCESS_KEY"),
        os.environ.get("AWS_REGION")
    ])
    return {
        "status": "ok", 
        "timestamp": datetime.utcnow().isoformat(),
        "aws_configured": aws_configured
    }

@app.get("/", tags=["Geral"])
async def raiz():
    return {"mensagem": "Bem-vindo à API de Controle Hídrico!"}

def buscar_historico(user_id: str, limit: int = 200) -> List[dict]:
    try:
        response = table_registros.query(
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": f"USER#{user_id}"},
            Limit=limit,
            ScanIndexForward=False
        )
        items = response.get("Items", [])
        # Converter Decimal para float
        for item in items:
            for key, value in item.items():
                if hasattr(value, 'to_eng_string'): # Checa se é Decimal sem importar
                    item[key] = float(value)
        return items
    except Exception as e:
        logger.error(f"Erro ao buscar histórico: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao acessar DynamoDB: {str(e)}")

def calcular_previsao_cateterismo(registros: List[dict]) -> Optional[dict]:
    if not registros:
        return None

    # Ordenar registros por horário
    try:
        registros_ordenados = sorted(registros, key=lambda x: datetime.fromisoformat(x['horario'].replace('Z', '+00:00')))
    except Exception as e:
        logger.error(f"Erro ao ordenar registros: {str(e)}")
        return None

    cateterismos = []
    for i, registro in enumerate(registros_ordenados):
        if registro.get('urineType') == 1:
            cateterismos.append({'index': i, 'horario': datetime.fromisoformat(registro['horario'].replace('Z', '+00:00'))})

    if len(cateterismos) < 2:
        return None

    intervalos_liquido = []
    for i in range(len(cateterismos) - 1):
        start_index = cateterismos[i]['index']
        end_index = cateterismos[i+1]['index']
        
        liquido_consumido = 0
        for j in range(start_index, end_index):
            liquido_consumido += float(registros_ordenados[j].get('quantidadeLiquidoM', 0) or 0)
        intervalos_liquido.append(liquido_consumido)

    if not intervalos_liquido:
        return None

    media_liquido_entre_cateterismos = sum(intervalos_liquido) / len(intervalos_liquido)

    ultimo_cateterismo_index = cateterismos[-1]['index']
    liquido_desde_ultimo_cateterismo = 0
    for i in range(ultimo_cateterismo_index, len(registros_ordenados)):
        liquido_desde_ultimo_cateterismo += float(registros_ordenados[i].get('quantidadeLiquidoM', 0) or 0)

    liquido_restante = media_liquido_entre_cateterismos - liquido_desde_ultimo_cateterismo

    if liquido_restante <= 0:
        return {"previsao": "Cateterismo iminente ou já deveria ter ocorrido.", "liquido_restante_ml": 0}

    duracoes_cateterismo = []
    for i in range(len(cateterismos) - 1):
        duracao = cateterismos[i+1]['horario'] - cateterismos[i]['horario']
        duracoes_cateterismo.append(duracao.total_seconds())
    
    media_duracao_segundos = sum(duracoes_cateterismo) / len(duracoes_cateterismo) if duracoes_cateterismo else 0

    if media_duracao_segundos == 0:
        return {"previsao": "Dados de duração insuficientes.", "liquido_restante_ml": liquido_restante}

    taxa_ingestao_ml_por_segundo = media_liquido_entre_cateterismos / media_duracao_segundos

    if taxa_ingestao_ml_por_segundo <= 0:
        return {"previsao": "Taxa de ingestão inválida.", "liquido_restante_ml": liquido_restante}

    tempo_restante_segundos = liquido_restante / taxa_ingestao_ml_por_segundo
    tempo_restante_timedelta = timedelta(seconds=tempo_restante_segundos)
    proximo_horario_previsto = cateterismos[-1]['horario'] + tempo_restante_timedelta

    return {
        "previsao": "Tempo estimado para o próximo cateterismo",
        "tempo_restante": str(tempo_restante_timedelta),
        "proximo_horario_previsto": proximo_horario_previsto.isoformat(),
        "liquido_restante_ml": round(liquido_restante, 2),
        "media_liquido_entre_cateterismos_ml": round(media_liquido_entre_cateterismos, 2)
    }

@app.get("/prever-cateterismo/{user_id}", tags=["Previsão"])
async def prever_cateterismo(user_id: str):
    registros = buscar_historico(user_id, limit=200)
    if not registros:
        raise HTTPException(status_code=404, detail="Nenhum registro encontrado para o usuário.")
    
    previsao = calcular_previsao_cateterismo(registros)
    if previsao is None:
        raise HTTPException(status_code=404, detail="Não há dados suficientes para prever o cateterismo.")
    
    return previsao

handler = Mangum(app)
