# HMT Gandaberunda Stock Sentinel 🦅⌚

An autonomous, personal stock monitoring system that discovers and tracks every **HMT Gandaberunda** watch across both official HMT websites and alerts you via **Telegram** the moment a matching watch becomes available to purchase.

Designed with conservative stock classification, dynamic product discovery, state persistence across runs, and zero ongoing cloud costs.

---

## Table of Contents

1. [Monitored Websites & Scope](#monitored-websites--scope)
2. [How It Works](#how-it-works)
   - [Dynamic Discovery](#1-dynamic-discovery)
   - [Conservative Availability Classification](#2-conservative-availability-classification)
   - [Restock Detection & Deduplication](#3-restock-detection--deduplication)
3. [Prerequisites](#prerequisites)
4. [Local Setup & Commands](#local-setup--commands)
5. [Telegram Bot Setup Walkthrough](#telegram-bot-setup-walkthrough)
6. [Cloud Deployment (GitHub Actions)](#cloud-deployment-github-actions)
7. [CLI Reference](#cli-reference)
8. [Automated Testing](#automated-testing)
9. [Troubleshooting Guide](#troubleshooting-guide)
10. [Limitations & Operational Realities](#limitations--operational-realities)

---

## Monitored Websites & Scope

The Sentinel monitors both independent official HMT digital storefronts:

| Website | Priority | Store Technology | Verification Status |
| :--- | :--- | :--- | :--- |
| **`https://hmtwatches.store/`** | **Primary** (Checked 1st) | Amazon SmartBiz (Next.js) | Verified live (Dynamic collection & Next.js catalog) |
| **`https://www.hmtwatches.in/`** | **Secondary** (Independent) | Custom PHP / Laravel Storefront | Verified live (Collection API 64 & Product Overview) |

### Monitored Variants
The monitor dynamically matches **all** Gandaberunda watches:
- Men's and Women's models
- Metal bracelets and leather straps
- Gold, silver, yellow, and white dial configurations
- All model reference numbers (`JLGG 01`, `JLGL 01`, `JLSS 01`, `JLSL 01`, etc.)
- Newly released models as soon as they appear in collection listings or sitemaps

> **Independent Isolation**: The two domains have completely separate catalogs. A restock or failure on one domain never interferes with or invalidates monitoring on the other.

---

## How It Works

### 1. Dynamic Discovery
No hardcoded product URLs. Discovery runs dynamically on every execution:
- **`hmtwatches.store`**: Inspects homepage `__NEXT_DATA__` JSON for `allCollections` matching Gandaberunda (`collection/6581423c-58b1-45c3-8695-202718942368/GandaBerunda`), checks `/sitemap.xml`, and extracts active product SKUs.
- **`hmtwatches.in`**: Queries the collection filter API (`POST /filter_products_collections` with `collection_val=64`), automatically handles pagination, and extracts product identifiers from `notifyMe(ID)` controls and URLs.

### 2. Conservative Availability Classification
Stock is categorized into four strict states:

- **`IN_STOCK`**: Credible evidence that the watch can currently be purchased (enabled *Add to Cart* / *Buy Now* button; `isBuyable: true` with positive inventory).
- **`OUT_OF_STOCK`**: Explicit evidence of unavailability (disabled purchase controls, `Out of Stock` / `Sold Out` labels, or `isBuyable: false`).
- **`COMING_SOON`**: Explicitly marked as upcoming / launching soon (`Coming Soon` label).
- **`UNKNOWN`**: Network error, timeout, or conflicting signals. Preserves previously verified reliable availability without triggering false alerts.

> **Safety Invariants**:
> - A page loading successfully does **not** mean the product is in stock.
> - A visible price does **not** mean the product is in stock.
> - A `Notify Me` button means the product is **out of stock**.
> - `Coming Soon` will **never** trigger a restock alert.

### 3. Restock Detection & Deduplication

```
                  ┌──────────────┐
                  │ Product Seen │
                  └──────┬───────┘
                         │
        ┌────────────────┴────────────────┐
        ▼                                 ▼
   [OUT_OF_STOCK / COMING_SOON]      [IN_STOCK]
        │                                 │
        │ Recorded silently               │
        │ (No alert)                      ▼
        │                    [Send Telegram Alert]
        │                         (Initial stock)
        │                                 │
        ▼                                 ▼
[Restock Transition]            [Remains IN_STOCK]
OOS ──► IN_STOCK                (No duplicate alerts)
        │
        ▼
[Send Telegram Alert]
```

Notifications are delivered **only** on meaningful availability transitions:
1. `OUT_OF_STOCK` $\rightarrow$ `IN_STOCK` (Restock Alert)
2. `COMING_SOON` $\rightarrow$ `IN_STOCK` (Launch Alert)
3. Newly discovered product that is already `IN_STOCK` (Initial Stock Alert)

---

## Prerequisites

- **Python 3.11+**
- **Git**
- A **Telegram account** (free)
- A **GitHub account** (free, for automated 10-minute cloud monitoring)

---

## Local Setup & Commands

### 1. Clone & create virtual environment

```bash
git clone https://github.com/<your-username>/hmt-gandaberunda-stock-sentinel.git
cd hmt-gandaberunda-stock-sentinel

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -e ".[dev]"
```

### 3. Configure environment variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit `.env` with your preferred settings:

```ini
TELEGRAM_BOT_TOKEN=<your_bot_token_from_botfather>
TELEGRAM_CHAT_ID=<your_numeric_chat_id>
NOTIFY_ON_FAILURE=0
REQUEST_TIMEOUT=25
MAX_RETRIES=3
LOG_LEVEL=INFO
DRY_RUN=0
ENABLE_STORE=1
ENABLE_IN=1
STATE_FILE=state.json
```

### 4. Run automated tests

```bash
python -m pytest -v
```

All 78 tests run using local fixtures and mocks (zero live network requests).

### 5. Run dynamic discovery only (Safe inspection)

```bash
python -m hmt_sentinel.cli discover
```

Discovers all matching Gandaberunda watches live from both websites and prints their current availability without sending alerts or saving state.

### 6. Run a dry-run monitoring cycle

```bash
python -m hmt_sentinel.cli dry-run
```

Performs a full monitoring run, updates `state.json`, but logs notification messages locally instead of dispatching to Telegram.

---

## Telegram Bot Setup Walkthrough

Setting up your Telegram alerts takes under 3 minutes and is 100% free.

### Step 1: Create a bot with BotFather
1. Open your Telegram app and search for **`@BotFather`** (ensure it has the official blue verification checkmark).
2. Start the chat and send the command:
   ```text
   /newbot
   ```
3. BotFather will ask for a display name (e.g., `HMT Watch Sentinel`).
4. BotFather will ask for a unique username ending in `bot` (e.g., `MyHmtGandaberundaBot`).
5. BotFather will reply with your **Bot Token** formatted like:
   ```text
   7123456789:AAFnX...your_unique_token_here...
   ```
   > 🔒 **Security Notice**: Never share this token publicly or commit it to GitHub.

### Step 2: Get your Telegram Chat ID
1. Search for **`@userinfobot`** in Telegram and click **Start**.
2. It will instantly reply with your account information, including your numeric **`Id`** (e.g., `123456789`).
3. Now, open the chat with **your newly created bot** from Step 1 and click **Start** (or send `/start`). This allows the bot to message you.

### Step 3: Test your credentials locally
Add your credentials to `.env`:
```ini
TELEGRAM_BOT_TOKEN=7123456789:AAFnX...
TELEGRAM_CHAT_ID=123456789
```

Run the built-in verification command:
```bash
python -m hmt_sentinel.cli telegram-test
```

You should instantly receive a verification message on Telegram:
```text
✅ HMT GANDABERUNDA SENTINEL — TEST NOTIFICATION

Your Telegram bot and chat configuration is active and working.
Timestamp: 27 Oct 2026, 09:50:00 PM IST
Status: System ready to monitor hmtwatches.store and hmtwatches.in
```

---

## Cloud Deployment (GitHub Actions)

Deploying to GitHub Actions gives you continuous monitoring every 10 minutes without keeping your computer on.

### Step 1: Push repository to GitHub
```bash
git remote add origin https://github.com/<your-username>/hmt-gandaberunda-stock-sentinel.git
git branch -M main
git push -u origin main
```

### Step 2: Add GitHub Secrets
1. Go to your repository on GitHub.
2. Navigate to **Settings** $\rightarrow$ **Secrets and variables** $\rightarrow$ **Actions**.
3. Under **Repository secrets**, click **New repository secret**:
   - Name: `TELEGRAM_BOT_TOKEN`
   - Value: `your_bot_token_here`
4. Click **New repository secret** again:
   - Name: `TELEGRAM_CHAT_ID`
   - Value: `your_numeric_chat_id_here`

### Step 3: Enable Workflow Permissions for State Persistence
The workflow automatically commits `state.json` back to the repository so your state survives across runner executions:
1. In repository **Settings**, go to **Actions** $\rightarrow$ **General**.
2. Scroll to **Workflow permissions**.
3. Select **Read and write permissions**.
4. Check **Allow GitHub Actions to create and approve pull requests**.
5. Click **Save**.

### Step 4: Run manual test on GitHub Actions
1. Go to the **Actions** tab in your GitHub repository.
2. In the left sidebar, click **Stock Sentinel Monitor**.
3. Click **Run workflow** $\rightarrow$ Check **Run in dry-run mode** (optional) $\rightarrow$ Click green **Run workflow** button.
4. Click into the workflow run to view the execution summary.

The monitor will now run automatically **every 10 minutes** via cron schedule.

---

## CLI Reference

| Command | Description |
| :--- | :--- |
| `python -m hmt_sentinel.cli monitor` | Executes a complete monitoring run, updates state, and sends alerts for confirmed restocks. |
| `python -m hmt_sentinel.cli discover` | Dynamic discovery only; prints all found Gandaberunda watches without modifying state. |
| `python -m hmt_sentinel.cli dry-run` | Runs full monitoring cycle without dispatching real Telegram messages. |
| `python -m hmt_sentinel.cli telegram-test` | Sends a one-off verification alert to your Telegram chat. |
| `python -m hmt_sentinel.cli status` | Displays all currently tracked watches, model numbers, prices, and stock states. |
| `python -m hmt_sentinel.cli test` | Runs the automated pytest suite (78 tests). |

---

## Sample Restock Alert

When a restock occurs, Telegram delivers:

```text
🎉 HMT GANDABERUNDA RESTOCK DETECTED

Product: HMT Women's Gandaberunda JLGG - 01 White
Model: JLGG 01
Price: ₹2599
Website: hmtwatches.store
Status: IN_STOCK
Detected at: 27 Oct 2026, 09:50:42 PM IST
Buy now: https://www.hmtwatches.store/product/50782856-6a30-4182-98c5-845fcab258d3
```

---

## Automated Testing

The Sentinel features 78 test cases across 5 dedicated test modules:

```text
tests/
├── test_matching.py       # 29 tests: spelling variants, hyphenation, truncated listing cards, URL normalization
├── test_availability.py   # 15 tests: in-stock, out-of-stock, coming-soon, disabled buttons, conflict handling
├── test_discovery.py      #  6 tests: Next.js __NEXT_DATA__, sitemaps, collection APIs, pagination, error isolation
├── test_state.py          # 13 tests: transitions, restock detection, deduplication, corrupt state recovery, domain isolation
└── test_notifications.py  #  8 tests: Telegram API retries, 429 rate limit backoff, formatting, dry-run
```

Run test suite:
```bash
python -m pytest -v
```

---

## Troubleshooting Guide

| Issue | Cause | Solution |
| :--- | :--- | :--- |
| **`TELEGRAM_BOT_TOKEN is not set`** | Missing environment variable | Create a `.env` file from `.env.example` locally, or add repository secrets on GitHub. |
| **Telegram test fails (403 Forbidden)** | You haven't started a chat with your bot | Open your Telegram bot in the app and press **Start** / send `/start`. |
| **`state.json` not saving in GitHub Actions** | Actions lacks write permission | Go to **Settings $\rightarrow$ Actions $\rightarrow$ General $\rightarrow$ Workflow permissions** and select **Read and write permissions**. |
| **No alerts received despite checking** | Watch is currently out of stock or coming soon | Alerts only trigger when status transitions to `IN_STOCK`. Run `python -m hmt_sentinel.cli status` to view current recorded states. |
| **Corrupted `state.json`** | System interrupted during disk write | The state engine automatically loads from `state.json.bak` if `state.json` is unparseable. |

---

## Limitations & Operational Realities

1. **Interval Polling**: GitHub Actions cron schedules run approximately every 10 minutes. During periods of heavy GitHub platform load, schedules may experience short delays.
2. **Flash Restocks**: Popular HMT limited releases occasionally sell out within 2–5 minutes. The Sentinel notifies you immediately upon detecting stock on its check cycle, but cannot guarantee that inventory remains available until checkout is completed.
3. **No Checkout Automation**: The Sentinel respects website integrity and acts strictly as an observational alert system. It does not automate cart checkout or bypass website controls.
