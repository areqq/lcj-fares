#!/usr/bin/env bash
# Popychacz kolejki pomiarów (lokalny cron) — uzupełnia cron GitHuba, który pomija część uruchomień.
# Co wywołanie: aktualizuje lokalne repo, sprawdza tą samą regułą co workflow (lcjfares/schedule.py),
# czy któreś lotnisko czeka; jeśli tak i nic nie leci — odpala workflow w trybie auto.
# Wymaga zalogowanego `gh` (token zostaje w ~/.config/gh, nie w repo).
#
# crontab:  47 * * * * /home/areq/lcj-fares/tools/kick-queue.sh >> $HOME/.cache/lcj-fares-kick.log 2>&1
set -uo pipefail
REPO=areqq/lcj-fares
DIR=$(cd "$(dirname "$0")/.." && pwd)
ts() { date -u +%FT%TZ; }

cd "$DIR" || exit 1
if ! git pull -q --ff-only 2>/dev/null; then
  echo "$(ts) git pull się nie udał (lokalne zmiany?) — sprawdzam na nieaktualnych danych"
fi
due=$(python3 -m lcjfares.schedule data)
if [ -z "$due" ]; then
  echo "$(ts) nic nie czeka"; exit 0
fi
busy=$(gh run list -R "$REPO" -w collect.yml -L 10 --json status -q '[.[] | select(.status != "completed")] | length') || {
  echo "$(ts) gh run list nie działa (brak sieci / logowania?)"; exit 1; }
if [ "$busy" != "0" ]; then
  echo "$(ts) czekają: $due — ale run już w toku/kolejce ($busy), pomijam"; exit 0
fi
gh workflow run collect.yml -R "$REPO" -f airport=auto && echo "$(ts) czekają: $due — uruchomiono workflow (auto)"
