# KQL Dashboard Queries for Application Insights

Kusto Query Language (KQL) queries for monitoring the NLP-to-SQL Azure Harness in Azure Application Insights.

## 1. Request Rate (Per Minute)

Tracks the incoming request rate to the `/api/v1/query` endpoint, aggregated per minute.

```kql
requests
| where name == "POST /api/v1/query"
| summarize RequestCount = count() by bin(timestamp, 1m)
| order by timestamp desc
| render timechart
```

## 2. Error Rate (By Status Code)

Shows the distribution of HTTP status codes over time, highlighting error responses (4xx/5xx).

```kql
requests
| where timestamp > ago(24h)
| summarize Count = count() by resultCode, bin(timestamp, 5m)
| order by timestamp desc
| render barchart
```

## 3. P50/P95/P99 Latency

End-to-end latency percentiles for the query endpoint to identify performance degradation.

```kql
requests
| where name == "POST /api/v1/query"
| where timestamp > ago(24h)
| summarize
    P50 = percentile(duration, 50),
    P95 = percentile(duration, 95),
    P99 = percentile(duration, 99)
    by bin(timestamp, 5m)
| order by timestamp desc
| render timechart
```

## 4. Cache Hit Rate

Ratio of semantic cache hits vs. misses over time, indicating cost savings and latency reduction.

```kql
customEvents
| where name in ("cache_hit", "query_received")
| where timestamp > ago(24h)
| summarize
    TotalQueries = countif(name == "query_received"),
    CacheHits = countif(name == "cache_hit")
    by bin(timestamp, 15m)
| extend HitRate = round(100.0 * CacheHits / TotalQueries, 2)
| project timestamp, TotalQueries, CacheHits, HitRate
| order by timestamp desc
| render timechart
```

## 5. Token Consumption Over Time

Tracks prompt and completion token usage across all LLM invocations to monitor cost trends.

```kql
customEvents
| where name == "sql_generated"
| where timestamp > ago(7d)
| extend PromptTokens = toint(customDimensions["prompt_tokens"])
| extend CompletionTokens = toint(customDimensions["completion_tokens"])
| summarize
    TotalPromptTokens = sum(PromptTokens),
    TotalCompletionTokens = sum(CompletionTokens),
    TotalTokens = sum(PromptTokens) + sum(CompletionTokens)
    by bin(timestamp, 1h)
| order by timestamp desc
| render timechart
```

## 6. Cost Per Query (Estimated)

Estimated USD cost per query based on token consumption and model pricing.

```kql
customEvents
| where name == "cost_estimate"
| where timestamp > ago(7d)
| extend CostUSD = todouble(customDimensions["cost_usd"])
| extend Model = tostring(customDimensions["model"])
| summarize
    AvgCost = round(avg(CostUSD), 6),
    TotalCost = round(sum(CostUSD), 4),
    QueryCount = count()
    by bin(timestamp, 1h), Model
| order by timestamp desc
| render timechart
```

## 7. Prompt Variant Distribution (A/B Testing)

Tracks which prompt template version is being used and its performance characteristics.

```kql
customEvents
| where name == "sql_generated"
| where timestamp > ago(7d)
| extend PromptVariant = tostring(customDimensions["prompt_variant"])
| summarize
    Count = count(),
    AvgLatencyMs = avg(todouble(customDimensions["latency_ms"]))
    by PromptVariant, bin(timestamp, 1h)
| order by timestamp desc
| render barchart
```
