# Azure Service Configuration — Step-by-Step Checklist

This is a hands-on guide to configure all Azure services for the NLP-to-SQL Harness.
Execute these steps in order. Each step has a ✅ verification check at the end.

> **Platform:** Windows (PowerShell / Azure Portal)
> **Estimated Time:** 45-60 minutes
> **Cost:** ~$5-10/day on pay-as-you-go (can be deleted after demo)

---

## Phase 0: Prerequisites

Before you start, confirm you have:

- [ ] **Azure Subscription** (free trial works for most services)
- [ ] **Azure OpenAI access approved** — [Request here](https://aka.ms/oai/access) (may take 1-2 days)
- [ ] **Azure CLI installed** — Run `az --version` (need 2.50+)
- [ ] **Python 3.11+** installed — Run `python --version`
- [ ] **ODBC Driver 18** installed — [Download here](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)

### Install Azure CLI (if needed)
```powershell
winget install -e --id Microsoft.AzureCLI
```

---

## Phase 1: Azure Login & Resource Group

### Step 1.1 — Login to Azure
```powershell
az login
```
This opens your browser. Sign in with your Azure account.

### Step 1.2 — Set your subscription
```powershell
# List subscriptions
az account list --output table

# Set the one you want to use
az account set --subscription "<your-subscription-id>"
```

### Step 1.3 — Create Resource Group
```powershell
az group create --name rg-nlptosql-dev --location eastus2
```

> **Why eastus2?** It has the best availability for Azure OpenAI models. You can use `eastus`, `westus2`, or `swedencentral` as alternatives.

✅ **Verify:** `az group show --name rg-nlptosql-dev --query name`

---

## Phase 2: Azure OpenAI Service

### Step 2.1 — Create Azure OpenAI resource
```powershell
az cognitiveservices account create `
  --name nlptosql-dev-openai `
  --resource-group rg-nlptosql-dev `
  --location eastus2 `
  --kind OpenAI `
  --sku S0
```

### Step 2.2 — Deploy GPT-4o model
```powershell
az cognitiveservices account deployment create `
  --name nlptosql-dev-openai `
  --resource-group rg-nlptosql-dev `
  --deployment-name gpt-4o `
  --model-name gpt-4o `
  --model-version "2024-05-13" `
  --model-format OpenAI `
  --sku-capacity 30 `
  --sku-name Standard
```

### Step 2.3 — Deploy GPT-4 Turbo (fallback)
```powershell
az cognitiveservices account deployment create `
  --name nlptosql-dev-openai `
  --resource-group rg-nlptosql-dev `
  --deployment-name gpt-4-turbo `
  --model-name gpt-4 `
  --model-version "turbo-2024-04-09" `
  --model-format OpenAI `
  --sku-capacity 30 `
  --sku-name Standard
```

### Step 2.4 — Deploy Embedding model
```powershell
az cognitiveservices account deployment create `
  --name nlptosql-dev-openai `
  --resource-group rg-nlptosql-dev `
  --deployment-name text-embedding-ada-002 `
  --model-name text-embedding-ada-002 `
  --model-version "2" `
  --model-format OpenAI `
  --sku-capacity 30 `
  --sku-name Standard
```

### Step 2.5 — Get endpoint and key
```powershell
# Get endpoint
az cognitiveservices account show `
  --name nlptosql-dev-openai `
  --resource-group rg-nlptosql-dev `
  --query properties.endpoint --output tsv

# Get API key
az cognitiveservices account keys list `
  --name nlptosql-dev-openai `
  --resource-group rg-nlptosql-dev `
  --query key1 --output tsv
```

📝 **Save these values** — you'll need them for `.env`:
- `AZURE_OPENAI_ENDPOINT` = the endpoint URL
- `AZURE_OPENAI_API_KEY` = the key

✅ **Verify:**
```powershell
az cognitiveservices account deployment list `
  --name nlptosql-dev-openai `
  --resource-group rg-nlptosql-dev `
  --output table
```
Should show 3 deployments: gpt-4o, gpt-4-turbo, text-embedding-ada-002

---

## Phase 3: Azure AI Search

### Step 3.1 — Create Search service
```powershell
az search service create `
  --name nlptosql-dev-search `
  --resource-group rg-nlptosql-dev `
  --location eastus2 `
  --sku basic
```

> **Note:** Basic SKU is required for vector search. Free tier does NOT support it.

### Step 3.2 — Get Search endpoint and key
```powershell
# Endpoint is: https://nlptosql-dev-search.search.windows.net

# Get admin key
az search admin-key show `
  --resource-group rg-nlptosql-dev `
  --service-name nlptosql-dev-search `
  --query primaryKey --output tsv
```

📝 **Save:**
- `AZURE_SEARCH_ENDPOINT` = `https://nlptosql-dev-search.search.windows.net`
- `AZURE_SEARCH_API_KEY` = the admin key

### Step 3.3 — Create Semantic Cache Index

Go to **Azure Portal** → your Search service → **Indexes** → **Add index (JSON)**

Paste this JSON:
```json
{
  "name": "semantic-cache-index",
  "fields": [
    {"name": "id", "type": "Edm.String", "key": true, "filterable": true},
    {"name": "nl_query", "type": "Edm.String", "searchable": true},
    {"name": "embedding", "type": "Collection(Edm.Single)", "searchable": true, "dimensions": 1536, "vectorSearchProfile": "default-profile"},
    {"name": "generated_sql", "type": "Edm.String", "searchable": false},
    {"name": "results", "type": "Edm.String", "searchable": false},
    {"name": "created_at", "type": "Edm.DateTimeOffset", "filterable": true},
    {"name": "ttl_seconds", "type": "Edm.Int32", "filterable": true}
  ],
  "vectorSearch": {
    "algorithms": [{"name": "hnsw-algo", "kind": "hnsw", "hnswParameters": {"m": 4, "efConstruction": 400, "efSearch": 500, "metric": "cosine"}}],
    "profiles": [{"name": "default-profile", "algorithm": "hnsw-algo"}]
  }
}
```

### Step 3.4 — Create Few-Shot Index

Same process, paste:
```json
{
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
}
```

✅ **Verify:** Both indexes appear in the Portal under your Search service → Indexes

---

## Phase 4: Azure SQL Database

### Step 4.1 — Create SQL Server
```powershell
az sql server create `
  --name nlptosql-dev-sql `
  --resource-group rg-nlptosql-dev `
  --location eastus2 `
  --admin-user sqladmin `
  --admin-password "<YourStrongPassword123!>"
```

### Step 4.2 — Create Database
```powershell
az sql db create `
  --name nlptosqldb `
  --resource-group rg-nlptosql-dev `
  --server nlptosql-dev-sql `
  --edition Basic `
  --capacity 5
```

### Step 4.3 — Allow your IP through firewall
```powershell
# Get your public IP
$myIp = (Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing).Content

az sql server firewall-rule create `
  --resource-group rg-nlptosql-dev `
  --server nlptosql-dev-sql `
  --name "LocalDev" `
  --start-ip-address $myIp `
  --end-ip-address $myIp
```

### Step 4.4 — Also allow Azure services
```powershell
az sql server firewall-rule create `
  --resource-group rg-nlptosql-dev `
  --server nlptosql-dev-sql `
  --name "AllowAzureServices" `
  --start-ip-address 0.0.0.0 `
  --end-ip-address 0.0.0.0
```

### Step 4.5 — Run seed scripts

Option A: Use **Azure Portal** → SQL Database → Query editor (preview)
- Paste contents of `data/seed/001_create_tables.sql` → Run
- Paste contents of `data/seed/002_insert_data.sql` → Run

Option B: Use **sqlcmd** from command line:
```powershell
sqlcmd -S nlptosql-dev-sql.database.windows.net -d nlptosqldb -U sqladmin -P "<password>" -i data\seed\001_create_tables.sql
sqlcmd -S nlptosql-dev-sql.database.windows.net -d nlptosqldb -U sqladmin -P "<password>" -i data\seed\002_insert_data.sql
```

📝 **Save for `.env`:**
- `SQL_CONNECTION_STRING` = `Driver={ODBC Driver 18 for SQL Server};Server=nlptosql-dev-sql.database.windows.net;Database=nlptosqldb;Uid=sqladmin;Pwd=<password>;Encrypt=yes;TrustServerCertificate=no;`

✅ **Verify:** Run in Query editor:
```sql
SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'
```
Should show 7 tables.

---

## Phase 5: Azure Cache for Redis

### Step 5.1 — Create Redis instance
```powershell
az redis create `
  --name nlptosql-dev-redis `
  --resource-group rg-nlptosql-dev `
  --location eastus2 `
  --sku Basic `
  --vm-size c0
```

> ⏳ This takes 15-20 minutes to provision. Continue with other steps while waiting.

### Step 5.2 — Get connection details (after provisioning completes)
```powershell
# Get host name
az redis show `
  --name nlptosql-dev-redis `
  --resource-group rg-nlptosql-dev `
  --query hostName --output tsv

# Get primary key
az redis list-keys `
  --name nlptosql-dev-redis `
  --resource-group rg-nlptosql-dev `
  --query primaryKey --output tsv
```

📝 **Save for `.env`:**
- `REDIS_CONNECTION_STRING` = `nlptosql-dev-redis.redis.cache.windows.net:6380,password=<key>,ssl=True,abortConnect=False`

✅ **Verify:** `az redis show --name nlptosql-dev-redis --resource-group rg-nlptosql-dev --query provisioningState`
Should return `Succeeded`

---

## Phase 6: Azure Blob Storage

### Step 6.1 — Create Storage Account
```powershell
az storage account create `
  --name nlptosqldevstorage `
  --resource-group rg-nlptosql-dev `
  --location eastus2 `
  --sku Standard_LRS
```

> **Note:** Storage account names must be globally unique, lowercase, no hyphens. Adjust if name is taken.

### Step 6.2 — Create containers
```powershell
az storage container create --name prompts --account-name nlptosqldevstorage --auth-mode login
az storage container create --name schema --account-name nlptosqldevstorage --auth-mode login
az storage container create --name evaluation --account-name nlptosqldevstorage --auth-mode login
az storage container create --name feedback --account-name nlptosqldevstorage --auth-mode login
```

### Step 6.3 — Upload files
```powershell
# Prompt templates
az storage blob upload --account-name nlptosqldevstorage --container-name prompts --name system_prompt_v1.txt --file prompts\system_prompt_v1.txt --auth-mode login
az storage blob upload --account-name nlptosqldevstorage --container-name prompts --name system_prompt_v2.txt --file prompts\system_prompt_v2.txt --auth-mode login
az storage blob upload --account-name nlptosqldevstorage --container-name prompts --name metadata.json --file prompts\metadata.json --auth-mode login

# Schema metadata
az storage blob upload --account-name nlptosqldevstorage --container-name schema --name schema_metadata.json --file data\schema_metadata.json --auth-mode login

# Evaluation test cases
az storage blob upload --account-name nlptosqldevstorage --container-name evaluation --name test_cases.json --file data\evaluation\test_cases.json --auth-mode login
```

📝 **Save for `.env`:**
- `AZURE_BLOB_STORAGE_URL` = `https://nlptosqldevstorage.blob.core.windows.net`

✅ **Verify:**
```powershell
az storage blob list --account-name nlptosqldevstorage --container-name prompts --auth-mode login --output table
```

---

## Phase 7: Application Insights

### Step 7.1 — Create Log Analytics Workspace
```powershell
az monitor log-analytics workspace create `
  --resource-group rg-nlptosql-dev `
  --workspace-name nlptosql-dev-logs `
  --location eastus2
```

### Step 7.2 — Create Application Insights
```powershell
az monitor app-insights component create `
  --app nlptosql-dev-insights `
  --resource-group rg-nlptosql-dev `
  --location eastus2 `
  --workspace (az monitor log-analytics workspace show --resource-group rg-nlptosql-dev --workspace-name nlptosql-dev-logs --query id --output tsv)
```

### Step 7.3 — Get connection string
```powershell
az monitor app-insights component show `
  --app nlptosql-dev-insights `
  --resource-group rg-nlptosql-dev `
  --query connectionString --output tsv
```

📝 **Save for `.env`:**
- `APPLICATIONINSIGHTS_CONNECTION_STRING` = the connection string

✅ **Verify:** Resource appears in Portal

---

## Phase 8: Azure Key Vault

### Step 8.1 — Create Key Vault
```powershell
az keyvault create `
  --name nlptosql-dev-kv `
  --resource-group rg-nlptosql-dev `
  --location eastus2
```

> **Note:** Key Vault names are globally unique. If taken, try `nlptosql-dev-kv-<random>`.

📝 **Save for `.env`:**
- `AZURE_KEY_VAULT_URL` = `https://nlptosql-dev-kv.vault.azure.net/`

✅ **Verify:** `az keyvault show --name nlptosql-dev-kv --query name`

---

## Phase 9: Seed Few-Shot Index

After all services are configured and `.env` is populated:

```powershell
cd "c:\Users\user\Azure Learn\Az_syst"
python scripts/seed_few_shot_index.py
```

This generates embeddings for the 20 curated examples and uploads them to Azure AI Search.

✅ **Verify:** Check the few-shot-index in Azure Portal → AI Search → Indexes → Document count should be 20.

---

## Phase 10: Configure .env File

Create your `.env` file with all the values collected above:

```powershell
Copy-Item .env.example .env
```

Then edit `.env` with your values. Here's what to fill in:

| Variable | Where to get it |
|----------|----------------|
| `AZURE_OPENAI_ENDPOINT` | Phase 2, Step 2.5 |
| `AZURE_OPENAI_API_KEY` | Phase 2, Step 2.5 |
| `AZURE_SEARCH_ENDPOINT` | Phase 3, Step 3.2 |
| `AZURE_SEARCH_API_KEY` | Phase 3, Step 3.2 |
| `SQL_CONNECTION_STRING` | Phase 4, Step 4.5 |
| `REDIS_CONNECTION_STRING` | Phase 5, Step 5.2 |
| `AZURE_BLOB_STORAGE_URL` | Phase 6, Step 6.1 |
| `AZURE_KEY_VAULT_URL` | Phase 8, Step 8.1 |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Phase 7, Step 7.3 |

Leave CLU fields empty (optional — keyword heuristics will be used as fallback).

---

## Phase 11: Test the Application

### Step 11.1 — Install Python dependencies
```powershell
cd "c:\Users\user\Azure Learn\Az_syst"
pip install -e ".[dev]"
```

### Step 11.2 — Run the API
```powershell
uvicorn src.api.main:app --reload --port 8000
```

### Step 11.3 — Test health endpoint
Open browser: http://localhost:8000/api/v1/health

Should return:
```json
{"status": "healthy", "version": "1.0.0", "timestamp": "..."}
```

### Step 11.4 — Test a query
```powershell
$headers = @{"Authorization" = "Bearer test-token"; "Content-Type" = "application/json"}
$body = '{"nl_query": "How many customers do we have?"}'
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/query" -Method POST -Headers $headers -Body $body
```

### Step 11.5 — Open the frontend
```powershell
python -m http.server 3000 --directory frontend
```
Open browser: http://localhost:3000

✅ **Verify:** You can submit a query and get results back.

---

## Phase 12: Run Evaluation Pipeline

```powershell
python evaluation/evaluate.py
```

This will:
1. Load 34 test cases
2. Generate SQL for each (requires Azure OpenAI running)
3. Report exact-match and execution-accuracy scores
4. Exit with code 0 if accuracy ≥ 80%

---

## Quick Reference — All Resources Created

| Resource | Name | Type |
|----------|------|------|
| Resource Group | `rg-nlptosql-dev` | Container |
| Azure OpenAI | `nlptosql-dev-openai` | GPT-4o + Turbo + Embeddings |
| AI Search | `nlptosql-dev-search` | Vector indexes |
| SQL Server | `nlptosql-dev-sql` | Database server |
| SQL Database | `nlptosqldb` | Business data (7 tables) |
| Redis Cache | `nlptosql-dev-redis` | Session + result cache |
| Storage Account | `nlptosqldevstorage` | Prompts + schema + eval data |
| App Insights | `nlptosql-dev-insights` | Monitoring |
| Key Vault | `nlptosql-dev-kv` | Secrets |

---

## Cleanup (When Done)

To delete everything and stop billing:
```powershell
az group delete --name rg-nlptosql-dev --yes --no-wait
```

This removes ALL resources in the group. Not reversible.
