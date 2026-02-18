# API de Controle Hídrico com FastAPI

Esta é uma API profissional de exemplo criada em Python utilizando o framework **FastAPI**.

## Funcionalidades
- **Healthcheck**: Verifica o status da API.
- **Previsão de Cateterismo**: Estima o tempo para o próximo cateterismo com base no histórico de ingestão de líquidos e eventos de cateterismo.
- **Integração com DynamoDB**: Busca dados de `controleHidrico`, `tb_parametros_paciente` e `tb_usuarios_controle_hidrico`.
- **Validação Automática**: Uso de Pydantic para garantir que os dados enviados estão corretos.
- **Documentação Interativa**: Swagger UI gerado automaticamente.

## Como Executar Localmente

1. **Instale as dependências**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure suas credenciais AWS**:
   Certifique-se de que suas credenciais AWS estejam configuradas localmente.

3. **Inicie o servidor**:
   ```bash
   uvicorn api.index:app --reload
   ```

## Deploy na Vercel

Esta API está configurada para deploy na Vercel usando Serverless Functions.

1. **Instale a Vercel CLI**: `npm i -g vercel`
2. **Faça login**: `vercel login`
3. **Deploy**: Execute `vercel` na raiz do projeto.
4. **Variáveis de Ambiente**: No painel da Vercel, configure as seguintes variáveis:
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`
   - `AWS_REGION` (ex: `us-east-1`)

A Vercel usará o arquivo `vercel.json` para rotear todas as requisições para `api/index.py`.

## Endpoints Principais

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/` | Mensagem de boas-vindas |
| GET | `/healthcheck` | Verifica o status da API |
| GET | `/prever-cateterismo/{user_id}` | Retorna a previsão do próximo cateterismo para um usuário |
