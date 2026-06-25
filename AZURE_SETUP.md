# Azure Setup Guide

Complete step-by-step guide for deploying the NLP-to-SQL Azure Harness infrastructure.

## Prerequisites

- **Azure Subscription** with Contributor access (or Owner for RBAC assignments)
- **Azure CLI** v2.50+ installed ([Install guide](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli))
- **Bicep CLI** v0.22+ (bundled with Azure CLI 2.50+)
- **Azure OpenAI access** approved for your subscription
- **ODBC Driver 18** for SQL Server (local development)
- **Python 3.11+** for running the application

## 1. Login and Set Subscription

```bash
az login
az account set --subscription "<your-subscription-id>"
```

## 2. Create Resource Group

```bash
az group create \
  --name rg-nlptosql-dev \
  --location eastus2
```

## 3. Deploy Infrastructure with Bicep

```bash
az deployment group create \
  --resource-group rg-nlptosql-dev \
  --template-file infra/main.bicep \
  --parameters infra/main.parameters.json \
  --parameters sqlAdminPassword="<your-secure-password>"
```

> **Note:** For production, use a Key Vault reference for `sqlAdminPassword` instead of passing it directly. Update `main.parameters.json` with your Key Vault resource ID.

### Retrieve Deployment Outputs

```bash
az deployment group show \
  --resource-group rg-nlptosql-dev \
  --name main \
  --query properties.outputs \
  --output json
```

Save these outputs — you'll need them for subsequent steps.

## 4. Populate Key Vault Secrets

```bash
KV_NAME=$(az deployment group show \
  --resource-group rg-nlptosql-dev \
  --name main \
  --query properties.outputs.keyVaultUri.value \
  --output tsv | sed 's|https://||;s|.vault.azure.net/||')

# Azure OpenAI API Key (if not using Managed Identity for local dev)
az keyvault secret set \
  --vault-name $KV_NAME \
  --name "azure-openai-api-key" \
  --value "<your-openai-api-key>"

# SQL Connection String
az keyvault secret set \
  --vault-name $KV_NAME \
  --name "sql-connection-string" \
  --value "Driver={ODBC Driver 18 for SQL Server};Server=<server>.database.windows.net;Database=nlptosqldb;Uid=sqladmin;Pwd=<password>;Encrypt=yes;TrustServerCertificate=no;"

# Redis Connection String
REDIS_KEY=$(az redis list-keys \
  --resource-group rg-nlptosql-dev \
  --name nlptosql-dev-redis \
  --query primaryKey --output tsv)

az keyvault secret set \
  --vault-name $KV_NAME \
  --name "redis-connection-string" \
  --value "nlptosql-dev-redis.redis.cache.windows.net:6380,password=${REDIS_KEY},ssl=True,abortConnect=False"

# Azure AI Search API Key
SEARCH_KEY=$(az search admin-key show \
  --resource-group rg-nlptosql-dev \
  --service-name nlptosql-dev-search \
  --query primaryKey --output tsv)

az keyvault secret set \
  --vault-name $KV_NAME \
  --name "azure-search-api-key" \
  --value "$SEARCH_KEY"

# Application Insights Connection String
APP_INSIGHTS_CS=$(az monitor app-insights component show \
  --resource-group rg-nlptosql-dev \
  --app nlptosql-dev-insights \
  --query connectionString --output tsv)

az keyvault secret set \
  --vault-name $KV_NAME \
  --name "applicationinsights-connection-string" \
  --value "$APP_INSIGHTS_CS"
```

## 5. Azure SQL Database Setup

### Add your IP to firewall

```bash
MY_IP=$(curl -s https://api.ipify.org)
az sql server firewall-rule create \
  --resource-group rg-nlptosql-dev \
  --server nlptosql-dev-sql \
  --name "LocalDev" \
  --start-ip-address $MY_IP \
  --end-ip-address $MY_IP
```

### Run seed scripts

```bash
# Using sqlcmd (install via: pip install mssql-cli or download from Microsoft)
sqlcmd -S nlptosql-dev-sql.database.windows.net \
  -d nlptosqldb \
  -U sqladmin \
  -P "<password>" \
  -i data/seed/001_create_tables.sql

sqlcmd -S nlptosql-dev-sql.database.windows.net \
  -d nlptosqldb \
  -U sqladmin \
  -P "<password>" \
  -i data/seed/002_insert_data.sql
```

### Verify tables created

```bash
sqlcmd -S nlptosql-dev-sql.database.windows.net \
  -d nlptosqldb \
  -U sqladmin \
  -P "<password>" \
  -Q "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'"
```

Expected output: `customers`, `products`, `orders`, `order_items`, `campaigns`, `campaign_conversions`, `support_tickets`

## 6. Azure AI Search Index Creation

### Create the Semantic Cache Index

```bash
SEARCH_ENDPOINT="https://nlptosql-dev-search.search.windows.net"

az rest --method PUT \
  --url "${SEARCH_ENDPOINT}/indexes/semantic-cache-index?api-version=2023-11-01" \
  --headers "Content-Type=application/json" "api-key=${SEARCH_KEY}" \
  --body '{
    "name": "semantic-cache-index",
    "fields": [
      {"name": "id", "type": "Edm.String", "key": true, "filterable": true},
      {"name": "nl_query", "type": "Edm.String", "searchable": true},
      {"name": "embedding", "type": "Collection(Edm.Single)", "searchable": true, "dimensions": 1536, "vectorSearchProfile": "default-profile"},
      {"name": "generated_sql", "type": "Edm.String", "searchable": false},
      {"name": "created_at", "type": "Edm.DateTimeOffset", "filterable": true},
      {"name": "ttl_seconds", "type": "Edm.Int32", "filterable": true}
    ],
    "vectorSearch": {
      "algorithms": [{"name": "hnsw-algo", "kind": "hnsw", "hnswParameters": {"m": 4, "efConstruction": 400, "efSearch": 500, "metric": "cosine"}}],
      "profiles": [{"name": "default-profile", "algorithm": "hnsw-algo"}]
    }
  }'
```

### Create the Few-Shot Examples Index

```bash
az rest --method PUT \
  --url "${SEARCH_ENDPOINT}/indexes/few-shot-index?api-version=2023-11-01" \
  --headers "Content-Type=application/json" "api-key=${SEARCH_KEY}" \
  --body '{
    "name": "few-shot-index",
    "fields": [
      {"name": "id", "type": "Edm.String", "key": true, "filterable": true},
      {"name": "nl_query", "type": "Edm.String", "searchable": true},
      {"name": "embedding", "type": "Collection(Edm.Single)", "searchable": true, "dimensions": 1536, "vectorSearchProfile": "default-profile"},
      {"name": "generated_sql", "type": "Edm.String", "searchable": false},
      {"name": "feedback_trace_id", "type": "Edm.String", "filterable": true},
      {"name": "promoted_at", "type": "Edm.DateTimeOffset", "filterable": true}
    ],
    "vectorSearch": {
      "algorithms": [{"name": "hnsw-algo", "kind": "hnsw", "hnswParameters": {"m": 4, "efConstruction": 400, "efSearch": 500, "metric": "cosine"}}],
      "profiles": [{"name": "default-profile", "algorithm": "hnsw-algo"}]
    }
  }'
```

## 7. Blob Storage Setup

### Upload prompt templates

```bash
STORAGE_ACCOUNT=$(az deployment group show \
  --resource-group rg-nlptosql-dev \
  --name main \
  --query properties.outputs.storageAccountName.value \
  --output tsv)

az storage blob upload \
  --account-name $STORAGE_ACCOUNT \
  --container-name prompts \
  --name system_prompt_v1.txt \
  --file prompts/system_prompt_v1.txt \
  --auth-mode login

az storage blob upload \
  --account-name $STORAGE_ACCOUNT \
  --container-name prompts \
  --name metadata.json \
  --file prompts/metadata.json \
  --auth-mode login
```

### Upload schema metadata

```bash
az storage blob upload \
  --account-name $STORAGE_ACCOUNT \
  --container-name schema \
  --name schema_metadata.json \
  --file data/schema_metadata.json \
  --auth-mode login
```

### Upload evaluation test cases

```bash
az storage blob upload \
  --account-name $STORAGE_ACCOUNT \
  --container-name evaluation \
  --name test_cases.json \
  --file data/evaluation/test_cases.json \
  --auth-mode login
```

## 8. Verification Steps

### Verify Azure OpenAI

```bash
az cognitiveservices account deployment list \
  --resource-group rg-nlptosql-dev \
  --name nlptosql-dev-openai \
  --output table
```

Expected: 3 deployments (gpt-4o, gpt-4-turbo, text-embedding-ada-002)

### Verify AI Search indexes

```bash
az rest --method GET \
  --url "${SEARCH_ENDPOINT}/indexes?api-version=2023-11-01" \
  --headers "api-key=${SEARCH_KEY}" \
  --query "value[].name"
```

Expected: `["semantic-cache-index", "few-shot-index"]`

### Verify Redis connectivity

```bash
az redis show \
  --resource-group rg-nlptosql-dev \
  --name nlptosql-dev-redis \
  --query "{name:name, provisioningState:provisioningState, hostName:hostName}" \
  --output table
```

### Verify App Service

```bash
APP_URL=$(az deployment group show \
  --resource-group rg-nlptosql-dev \
  --name main \
  --query properties.outputs.webAppUrl.value \
  --output tsv)

curl -s "${APP_URL}/health" | jq .
```

### Verify Key Vault access

```bash
az keyvault secret list --vault-name $KV_NAME --output table
```

## 9. Local Development Setup

For local development, create a `.env` file from the template:

```bash
cp .env.example .env
```

Fill in the values from your deployment outputs:

```bash
# Quick way to populate local .env from deployed resources
echo "AZURE_OPENAI_ENDPOINT=$(az cognitiveservices account show \
  --resource-group rg-nlptosql-dev \
  --name nlptosql-dev-openai \
  --query properties.endpoint --output tsv)" >> .env

echo "AZURE_SEARCH_ENDPOINT=https://nlptosql-dev-search.search.windows.net" >> .env

echo "AZURE_BLOB_STORAGE_URL=$(az storage account show \
  --resource-group rg-nlptosql-dev \
  --name $STORAGE_ACCOUNT \
  --query primaryEndpoints.blob --output tsv)" >> .env

echo "AZURE_KEY_VAULT_URL=$(az keyvault show \
  --resource-group rg-nlptosql-dev \
  --name $KV_NAME \
  --query properties.vaultUri --output tsv)" >> .env
```

Then install dependencies and run:

```bash
pip install -e ".[dev]"
uvicorn src.api.main:app --reload --port 8000
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `AuthorizationFailed` during deployment | Ensure you have Contributor + User Access Administrator roles on the resource group |
| OpenAI deployment fails | Verify your subscription has Azure OpenAI access approved and the region supports the models |
| SQL connection timeout | Check firewall rules include your IP and the App Service outbound IPs |
| Redis connection refused | Ensure SSL is enabled (`ssl=True`) and using port 6380 |
| Key Vault access denied | Verify RBAC role assignments propagated (can take up to 5 minutes) |
| AI Search index creation fails | Ensure the search service SKU supports vector search (Basic or higher) |

## Cost Management

For development, you can reduce costs by:
- Using `Free` tier for App Service (remove `alwaysOn`)
- Scaling Redis to `C0` Basic (already configured)
- Using `Basic` SQL Database tier (already configured)
- Reducing OpenAI model capacity in the Bicep parameters
