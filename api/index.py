from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from uuid import uuid4, UUID
import pandas as pd
from mangum import Mangum

import boto3
import os
from datetime import datetime, timedelta, timezone

app = FastAPI(
    title="API de Controle Hídrico",
    description="API para gerenciar o controle hídrico e prever cateterismo.",
    version="1.0.0"
)

# AWS config via environment
dynamodb = boto3.resource(
    "dynamodb",
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
)

table_registros = dynamodb.Table("controleHidrico")
table_parametros = dynamodb.Table("tb_parametros_paciente")
table_usuarios = dynamodb.Table("tb_usuarios_controle_hidrico")

@app.get("/healthcheck", tags=["Geral"])
async def healthcheck():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.get("/", tags=["Geral"])
async def raiz():
    return {"mensagem": "Bem-vindo à API de Controle Hídrico!"}


def buscar_peso_paciente(user_id: str) -> dict:
    response = table_usuarios.get_item(
        Key={
            "PK": f"USER#{user_id}",
            "SK": "PROFILE"
        }
    )
    item = response.get("Item")
    if not item:
        raise HTTPException(status_code=404, detail=f"Usuário USER#{user_id} com SK PROFILE não encontrado no DynamoDB")
    return {"peso": float(item.get("peso", 0)), "limiteVesical": float(item.get("limiteVesical", 0))}

def buscar_parametros(user_id: str) -> dict:
    response = table_parametros.get_item(
        Key={
            "PK": f"USER#{user_id}"
        }
    )
    item = response.get("Item")
    if not item:
        # Fallback padrão fisiológico se não encontrar parâmetros específicos
        return {"alpha": 0.7, "tau": 4.0, "basal": 5.0, "origem": "padrao"}
    return {
        "alpha": float(item.get("alpha", 0)),
        "tau": float(item.get("tau", 0)),
        "basal": float(item.get("basal", 0)),
        "origem": "treinado"
    }

def buscar_historico(user_id: str, limit: int = 200) -> List[dict]:
    response = table_registros.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": f"USER#{user_id}"},
        Limit=limit,
        ScanIndexForward=False # Para pegar os mais recentes primeiro
    )
    items = response.get("Items", [])
    # Converter Decimal para float para compatibilidade com Pydantic/JSON
    for item in items:
        for key, value in item.items():
            if isinstance(value, type(boto3.dynamodb.types.Decimal())):
                item[key] = float(value)
    return items


def calcular_previsao_cateterismo(registros: List[dict]) -> Optional[dict]:
    if not registros:
        return None

    # Ordenar registros por horário para garantir a sequência cronológica
    registros_ordenados = sorted(registros, key=lambda x: datetime.fromisoformat(x['horario']))

    cateterismos = []
    for i, registro in enumerate(registros_ordenados):
        if registro.get('urineType') == 1:
            cateterismos.append({'index': i, 'horario': datetime.fromisoformat(registro['horario'])})

    if len(cateterismos) < 2:
        return None # Não há cateterismos suficientes para calcular uma média

    intervalos_liquido = []
    for i in range(len(cateterismos) - 1):
        start_index = cateterismos[i]['index']
        end_index = cateterismos[i+1]['index']
        
        liquido_consumido = 0
        for j in range(start_index, end_index):
            liquido_consumido += registros_ordenados[j].get('quantidadeLiquidoM', 0)
        intervalos_liquido.append(liquido_consumido)

    if not intervalos_liquido:
        return None

    media_liquido_entre_cateterismos = sum(intervalos_liquido) / len(intervalos_liquido)

    # Calcular líquido consumido desde o último cateterismo
    ultimo_cateterismo_index = cateterismos[-1]['index']
    liquido_desde_ultimo_cateterismo = 0
    for i in range(ultimo_cateterismo_index, len(registros_ordenados)):
        liquido_desde_ultimo_cateterismo += registros_ordenados[i].get('quantidadeLiquidoM', 0)

    # Estimar o líquido restante para o próximo cateterismo
    liquido_restante = media_liquido_entre_cateterismos - liquido_desde_ultimo_cateterismo

    if liquido_restante <= 0:
        return {"previsao": "Cateterismo iminente ou já deveria ter ocorrido.", "liquido_restante_ml": 0}

    # Para estimar o tempo, precisamos de uma taxa de ingestão de líquidos. 
    # Como não temos essa informação diretamente, faremos uma estimativa simplificada.
    # Assumimos que a ingestão de líquidos é constante ao longo do tempo.
    # Esta é uma simplificação e pode ser melhorada com dados de ingestão em tempo real.
    
    # Calcular a duração média entre cateterismos
    duracoes_cateterismo = []
    for i in range(len(cateterismos) - 1):
        duracao = cateterismos[i+1]['horario'] - cateterismos[i]['horario']
        duracoes_cateterismo.append(duracao.total_seconds())
    
    media_duracao_segundos = sum(duracoes_cateterismo) / len(duracoes_cateterismo) if duracoes_cateterismo else 0

    if media_duracao_segundos == 0:
        return {"previsao": "Não foi possível estimar o tempo restante devido à falta de dados de duração.", "liquido_restante_ml": liquido_restante}

    # Estimar a taxa de ingestão de líquidos (ml/segundo)
    taxa_ingestao_ml_por_segundo = media_liquido_entre_cateterismos / media_duracao_segundos

    if taxa_ingestao_ml_por_segundo <= 0:
        return {"previsao": "Não foi possível estimar o tempo restante devido à taxa de ingestão de líquidos inválida.", "liquido_restante_ml": liquido_restante}

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
