# Notas de Pesquisa - API Controle Hídrico

## Estrutura das Tabelas DynamoDB
- **Tabela `controleHidrico`**:
  - PK: `USER#{user_id}`
  - SK: `REG#<timestamp>`
  - Campos: `tipoLiquidoId`, `quantidadeLiquidoM`, `observacoes`, `usuarioId`, `horario`, `quantidadeUrinaMl`, `urineType`.
- **Tabela `tb_parametros_paciente`**:
  - PK: `USER#{user_id}`
  - Campos: `alpha`, `tau`, `basal`.
- **Tabela `tb_usuarios_controle_hidrico`**:
  - PK: `USER#{user_id}`
  - SK: `PROFILE`
  - Campos: `peso`, `limiteVesical`.

## Lógica de Previsão Existente
1. Busca o peso e limite vesical do usuário.
2. Busca os parâmetros fisiológicos (`alpha`, `tau`, `basal`).
3. Busca o histórico de registros das últimas 24 horas.
4. Calcula a produção urinária futura baseada em um modelo matemático que considera o peso, parâmetros e o volume atual da bexiga (soma acumulada de urina).
5. O tempo para o próximo cateterismo é o momento em que o volume previsto atinge o `limiteVesical`.

## Requisito do Usuário
- Buscar os últimos 200 registros.
- Comparar a ingestão de líquidos após um cateterismo (`urineType = 1`) até o próximo.
- Criar uma média para prever o horário.
- Retornar quanto tempo falta.
