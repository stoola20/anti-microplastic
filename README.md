# Anti-Plastic EDC Bot

A LINE chatbot that analyzes personal care products and food containers for endocrine-disrupting chemicals (EDCs). Send a photo of an ingredient label or a product name, and receive a risk assessment in Traditional Chinese. Deployed on Railway.

![Python](https://img.shields.io/badge/python-3.11+-blue) ![License: MIT](https://img.shields.io/badge/License-MIT-yellow)

---

## Features

- **Image analysis** — Send a photo of an ingredient label; Claude Vision identifies EDC ingredients and rates the risk level
- **Product name analysis** — Send a product name; Tavily web search finds the INCI ingredient list, then Claude analyzes it via a tool-use loop (max 3 rounds)
- **Two-tier response** — A brief checklist is sent immediately; type `詳細` to retrieve the full analysis
- **Two product categories** — Personal care products (parabens, fragrance, UV absorbers, triclosan, MIT, BPA) and food containers (BPA/BPS, phthalates, PFAS, melamine)
- **Relevance detection** — Off-topic messages receive a polite redirect without triggering search or analysis

## Architecture

Four modules in `bot/`:

| Module | Responsibility |
|--------|----------------|
| `main.py` | FastAPI app; LINE signature verification (HMAC-SHA256); background task dispatch; Push API delivery |
| `analyzer.py` | Image analysis via Claude Vision; product name analysis via Tavily tool-use loop; markdown stripping |
| `prompts.py` | EDC system prompt; 6-category risk framework; `BRIEF` / `FULL` output format control |
| `state.py` | In-memory per-user session storage for full analysis retrieval |

**Data flow — image message:**

```
LINE → /webhook → download image → resize (Pillow, 1600px max)
→ base64 encode → Claude Vision (claude-sonnet-4-6)
→ { brief, full } → LINE Push API
```

**Data flow — text message:**

```
LINE → /webhook → Tavily search (tool-use, ≤3 rounds)
→ Claude analysis (claude-sonnet-4-6)
→ { brief, full } → LINE Push API
```

## Setup

### Prerequisites

- Python 3.11+
- [LINE Messaging API](https://developers.line.biz/) channel
- [Anthropic](https://console.anthropic.com/) API key
- [Tavily](https://tavily.com/) API key

### Install

```bash
git clone https://github.com/jessechen/anti-plastic.git
cd anti-plastic
pip install -r requirements.txt
```

### Environment variables

Copy `.env.example` to `.env` and fill in the values:

```
LINE_CHANNEL_SECRET=your_channel_secret_here
LINE_CHANNEL_ACCESS_TOKEN=your_channel_access_token_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
TAVILY_API_KEY=your_tavily_api_key_here
```

### Run locally

```bash
uvicorn bot.main:app --host 0.0.0.0 --port 8000
```

## Development

```bash
# Install dev dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Run all tests
pytest tests/ -v --tb=short

# Run a single test file
pytest tests/test_analyzer.py -v
```

Deploy to Railway: push to `main`; Railway reads `Procfile` and `railway.toml` automatically.
Health check endpoint: `GET /health`.

---

# Anti-Plastic EDC Bot（繁體中文）

一個 LINE 聊天機器人，分析個人護理品與食品容器中的環境荷爾蒙（EDC）風險。傳送成分標籤照片或輸入產品名稱，即可獲得繁體中文風險評估。部署於 Railway。

---

## 功能說明

- **圖片分析** — 傳送成分標籤照片，Claude Vision 識別 EDC 成分並評估風險等級
- **產品名稱分析** — 輸入產品名稱，透過 Tavily 搜尋 INCI 成分表，再由 Claude 進行工具呼叫迴圈分析（最多 3 輪）
- **兩段式回覆** — 立即傳送簡要清單；輸入 `詳細` 可取得完整分析
- **兩大產品類別** — 個人護理品（防腐劑、香精、紫外線吸收劑、三氯生、MIT、BPA）與食品容器（BPA/BPS、塑化劑、PFAS、美耐皿）
- **相關性判斷** — 與 EDC 無關的訊息將禮貌回覆，不觸發搜尋或分析

## 技術架構

`bot/` 目錄下共四個模組：

| 模組 | 職責 |
|------|------|
| `main.py` | FastAPI 應用程式；LINE 簽名驗證（HMAC-SHA256）；背景任務調度；Push API 傳送 |
| `analyzer.py` | Claude Vision 圖片分析；Tavily 工具呼叫迴圈產品分析；Markdown 移除 |
| `prompts.py` | EDC 系統提示；六類風險框架；`BRIEF` / `FULL` 輸出格式控制 |
| `state.py` | 基於記憶體的每位使用者完整分析暫存 |

**資料流 — 圖片訊息：**

```
LINE → /webhook → 下載圖片 → 縮放（Pillow，最大 1600px）
→ Base64 編碼 → Claude Vision（claude-sonnet-4-6）
→ { brief, full } → LINE Push API
```

**資料流 — 文字訊息：**

```
LINE → /webhook → Tavily 搜尋（工具呼叫，最多 3 輪）
→ Claude 分析（claude-sonnet-4-6）
→ { brief, full } → LINE Push API
```

## 安裝與設定

### 前置需求

- Python 3.11+
- [LINE Messaging API](https://developers.line.biz/) 頻道
- [Anthropic](https://console.anthropic.com/) API 金鑰
- [Tavily](https://tavily.com/) API 金鑰

### 安裝

```bash
git clone https://github.com/jessechen/anti-plastic.git
cd anti-plastic
pip install -r requirements.txt
```

### 環境變數

將 `.env.example` 複製為 `.env` 並填入對應的值：

```
LINE_CHANNEL_SECRET=your_channel_secret_here
LINE_CHANNEL_ACCESS_TOKEN=your_channel_access_token_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
TAVILY_API_KEY=your_tavily_api_key_here
```

### 本地啟動

```bash
uvicorn bot.main:app --host 0.0.0.0 --port 8000
```

## 開發指南

```bash
# 安裝開發依賴
pip install -r requirements.txt -r requirements-dev.txt

# 執行所有測試
pytest tests/ -v --tb=short

# 執行單一測試檔案
pytest tests/test_analyzer.py -v
```

部署至 Railway：推送至 `main` 分支，Railway 自動讀取 `Procfile` 與 `railway.toml`。
健康檢查端點：`GET /health`。
