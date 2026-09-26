#!/usr/bin/env python3
import os
import shutil
import subprocess  # nosec
import sys
from typing import List

import requests

# Color codes
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ask(prompt: str) -> str:
    """input() that treats a closed stdin (CI, a pipe) as no answer instead of crashing."""
    try:
        return input(prompt)
    except EOFError:
        print("(no answer)")
        return ""


def _true(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def print_banner():
    print(f"\n{BOLD}ReadyTrader-Crypto Setup Wizard 🛡️{RESET}")
    print("-----------------------------------")
    print("This script will help you prepare your environment for AI-agentic trading.\n")


def check_env_file() -> bool:
    if os.path.exists(".env"):
        print(f"{GREEN}[✓]{RESET} .env file found.")
        return True
    else:
        print(f"{YELLOW}[?]{RESET} .env file missing.")
        choice = ask("Do you want to create a .env from env.example now? (y/n): ")
        if choice.lower() == "y":
            shutil.copy("env.example", ".env")
            print(f"{GREEN}[✓]{RESET} .env file created. Please open it and fill in your keys later.")
            return True
        print("  Paper mode needs no .env. To configure one later: cp env.example .env")
    return False


def check_dependencies() -> List[str]:
    print("\nChecking Python dependencies...")
    missing = []
    # Key dependencies to check
    deps = ["fastmcp", "ccxt", "web3", "feedparser", "requests"]
    for dep in deps:
        try:
            __import__(dep)
            print(f"  {GREEN}[✓]{RESET} {dep}")
        except ImportError:
            print(f"  {RED}[✗]{RESET} {dep} (Missing)")
            missing.append(dep)
    return missing


def check_connectivity():
    print("\nChecking Network Connectivity...")
    targets = [
        ("Binance API", "https://api.binance.com/api/v3/ping"),
        ("CoinDesk RSS", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
        ("Fear & Greed Index", "https://api.alternative.me/fng/"),
    ]

    for name, url in targets:
        try:
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                print(f"  {GREEN}[✓]{RESET} {name} reachable.")
            elif res.status_code == 451:
                print(f"  {YELLOW}[?]{RESET} {name} returned 451: not available from this network. List exchanges you can reach in MARKETDATA_EXCHANGES.")
            else:
                print(f"  {YELLOW}[?]{RESET} {name} returned status {res.status_code}.")
        except Exception as e:
            print(f"  {RED}[✗]{RESET} {name} unreachable: {str(e)}")


def check_keys():
    print("\nChecking keys in .env...")
    if not os.path.exists(".env"):
        return

    from dotenv import load_dotenv

    load_dotenv()

    paper = _true("PAPER_MODE", True)
    live = (not paper) and _true("LIVE_TRADING_ENABLED", False)
    print(f"  {GREEN}[✓]{RESET} PAPER_MODE={'true' if paper else 'false'}, LIVE_TRADING_ENABLED={'true' if live else 'false'}")

    signer = (os.getenv("SIGNER_TYPE") or "null").strip().lower()
    if signer == "env_private_key":
        # A raw key in .env is for local development only; the server refuses it outside paper mode.
        colour = RED if (not paper or live) else YELLOW
        print(
            f"  {colour}[!]{RESET} SIGNER_TYPE=env_private_key keeps a raw key in .env: development only, "
            "refused for live trading (use keystore, remote or cb_mpc_2pc)."
        )
    else:
        print(f"  {GREEN}[✓]{RESET} SIGNER_TYPE={signer} (no raw private key needed).")

    has_cex_key = bool(os.getenv("CEX_API_KEY")) or any(k.startswith("CEX_") and k.endswith("_API_KEY") and os.getenv(k) for k in os.environ)
    if has_cex_key:
        print(f"  {GREEN}[✓]{RESET} Exchange API key detected.")
    elif paper:
        print(f"  {YELLOW}[-]{RESET} No exchange API key (not needed: paper orders fill in the paper account).")
    else:
        print(f"  {RED}[✗]{RESET} No exchange API key (CEX_API_KEY or CEX_<EXCHANGE>_API_KEY) and live trading is configured.")

    optional = {
        "NEWSAPI_KEY": "get_financial_news",
        "CRYPTOPANIC_API_KEY": "get_news",
        "TWITTER_BEARER_TOKEN": "get_social_sentiment (X)",
        "REDDIT_CLIENT_ID": "get_social_sentiment (Reddit)",
    }
    for key, tool in optional.items():
        if os.getenv(key):
            print(f"  {GREEN}[✓]{RESET} {key} detected.")
        else:
            print(f"  {YELLOW}[-]{RESET} {key} not set (optional: {tool} answers not_configured without it).")


def main():
    print_banner()

    check_env_file()
    missing_deps = check_dependencies()

    if missing_deps:
        print(f"\n{YELLOW}Missing dependencies detected.{RESET}")
        choice = ask("Would you like to install them now? (y/n): ")
        if choice.lower() == "y":
            print("Installing...")
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])  # nosec
            print(f"{GREEN}Installation complete.{RESET}")

    check_connectivity()
    check_keys()

    print(f"\n{BOLD}Setup Scan Complete!{RESET}")
    print("Next steps:")
    print(f"1. Open {BOLD}.env{RESET} and configure your SIGNER_TYPE and exchange keys.")
    print(f"2. Read {BOLD}docs/SENTIMENT.md{RESET} for intelligence feed setup.")
    print(f"3. Run {BOLD}python server.py{RESET} to start the MCP server.\n")


if __name__ == "__main__":
    main()
