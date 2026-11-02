# Aurora Signal Desk (read-only, paper trading only)
Setup from an Android phone (Chrome, "Desktop site" ON):
1. github.com -> sign up -> New repository -> name `aurora`, **Public**, tick "Add a README".
2. Add file -> Upload files: upload `scanner.py`, `requirements.txt`, then create `docs/index.html` and `.github/workflows/scan.yml` with Add file -> Create new file (type the full path in the name box, paste contents). Commit each.
3. Telegram: message @BotFather -> /newbot -> copy the token. Message your new bot "hi", then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy the number after `"chat":{"id":`.
4. Repo -> Settings -> Secrets and variables -> Actions -> New secret: `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID`. Never paste them into files.
5. Settings -> Pages -> Deploy from branch `main`, folder `/docs`. Settings -> Actions -> General -> Workflow permissions -> Read and write.
6. Actions tab -> scan -> Run workflow -> tick **demo** to test Telegram + dashboard. Run again without demo for live scans.
Dashboard: https://YOURNAME.github.io/aurora/
Edit settings (capital, fees, thresholds) in the CFG block at the top of scanner.py. Fee numbers are estimates - check IBKR.
