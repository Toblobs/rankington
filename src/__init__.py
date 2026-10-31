# __init__.py // @toblobs // 21.10.26
# for (rankington)

__version__ = "0.1.1"

START_ELO = 1000.0 # starting ranking for new players
K = 32.0 # initial adjustment factor

CSV_HEADERS = ["MatchID", "Player1", "Player2", "Player3", "Player4", "Team1Score", "Team2Score"]

with open("schema.txt") as f: SCHEMA = f.read()