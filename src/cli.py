# src > cli.py // @toblobs // 30.10.26
# for (rankington)

import argparse
import json
from pathlib import Path

from .core import Store, DomainError
from .scheduling import schedule

def main():
    
    parser = argparse.ArgumentParser(description = "rankington")
    parser.add_argument("--db", default = "data/badminton.sqlite3")
    
    sub = parser.add_subparsers(dest = "command", required = True)
    
    players = sub.add_parser("add-players")
    players.add_argument("names", nargs = "+")
    
    imp = sub.add_parser("import")
    imp.add_argument("week")
    imp.add_argument("csv", type = Path)
    imp.add_argument("--preview", action = "store_true")
    imp.add_argument("--replace", action = "store_true")
    
    rerate = sub.add_parser("rerate")
    rerate.add_argument("--preview", action = "store_true")
    
    sub.add_parser("leaderboard")
    
    backup = sub.add_parser("backup")
    backup.add_argument("destination")
    
    args = parser.parse_args()
    db = Store(args.db)
    
    try:
        if args.command == "add-players": result = [db.create_player(name) for name in args.names]
        
        elif args.command == "import": result = db.import_week(args.week, args.csv.read_text(encoding = "utf-8-sig"), preview = args.preview, replace = args.replace)
        elif args.command == "rerate": result = db.rerate(preview = args.preview)
        
        elif args.command == "backup":
            db.backup(args.destination)
            result = {"saved": args.destination}
        
        else: result = db.leaderboard()
        
        print(json.dumps(result, indent = 2))
        
    except DomainError as exc: parser.exit(1, f"Error: {exc}\n")

if __name__ == "__main__": main()
