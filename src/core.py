# src > core.py // @toblobs // 30.10.26
# for (rankington)

import sys
import io
import json
import math
import csv
import hashlib
import sqlite3
import unicodedata
import uuid
from contextlib import closing, contextmanager
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import List, Optional

from .__init__ import *

class DomainError(Exception):
    
    """
    Application exceptions.
    
    Attributes
    ----------
    message : `str`
        The exception message.
    status : `int`
        The exception HTTP status.
        
    Methods
    -------
    `__init__(self, message, status)`
        Creates the application exception.
    """
    
    def __init__(self, message: str, status: int = 422):
        
        super().__init__(message)
        self.status = status

# removal of whitespace and case problems for name lookups
def name_key(value): return unicodedata.normalize("NFC", " ".join(value.split())).casefold()

def expected(a: float, b: float) -> float:
    
    """
    ELO-like implementation of a win-probability formula.
    Limits `z` to interval [`-700`, `700`].
    
    Arguments
    ---------
    a : `float`
        The rating of the first team.
    b : `float`
        The rating of the second team.
    
    Returns
    -------
    `float` of the win probability for the first team.
    """
    
    z = max(-700, min(700, (b - a) * math.log(10) / 400))
    return 1 / (1 + math.exp(z)) # E = (1 / 1 + e^z)
    
def margin_multiplier(a: int, b: int) -> float:
    
    """
    Calculated the multiplier bonus based on the points difference.
    An 11-0 win gives a `2x` multiplier. A 2-point win gives a `1x` multiplier.
    Deuce (e.g. games going past 10-10) do not increase the bonus.
    
    Arguments
    ---------
    a : `float`
        The score of the first team.
    b : `float`
        The score of the second team.
    
    Returns
    -------
    `float of the multiplier bonus.
    """
    
    margin = min(9, max(0, abs(a - b) - 2)) / 9.0
    return 1.0 + margin

def valid_score(a: int, b: int) -> bool:
    
    """
    Checks if a given score for a match is valid.
    
    Arguments
    ---------
    a : `int`
        The score of the first team.
    b : `int`
        The score of the second team.
    
    Returns
    -------
    `True` if the score is valid under first-to-11 and deuce rules, else `False`.
    """
    
    hi, lo = max(a, b), min(a, b)
    bounds = ((hi == 11 and lo <= 9) or (hi >= 12 and hi - lo == 2))
    return (0 <= lo <= hi <= 2_147_483_647) and bounds

def parse_csv(text: str) -> List[dict]:
    
    """
    Takes a CSV-like string and parses it into a batch (week) of match scores.
    
    Arguments
    ---------
    text : `str`
        The string text to parse.
            
    Returns
    -------
    `List[dict]` of matches formatted {`match_id`, `names`, `scores`}.
    
    Raises
    ------
    `DomainError` if the CSV data has errors.
    """
    
    if len(text.encode("utf-8")) > 2_000_000: # length sanity check
        raise DomainError("CSV text exceeds 2MiB", 413)
    
    try:
        
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), strict = True)#
        
        if reader.fieldnames != CSV_HEADERS: # incorrect headers  
            raise DomainError("CSV headers must be exactly: " + ",".join(CSV_HEADERS))
        
        result, ids = [], set()
        
        for line, row in enumerate(reader, 2):
            
            if len(result) >= 10_000: # too many matches
                raise DomainError("Maximum of 10,000 matches a week")

            if None in row or any(v is None for v in row.values()): # missing a column
                raise DomainError(f"Row {line} has incorrect number of columns")
            
            match_id = row["MatchID"].strip()
            names = [row[f"Player{i}"].strip() for i in range(1, 5)] # get P1-4
    
            if not match_id or len(match_id) > 100 or match_id in ids: # bad MatchID
                raise DomainError(f"Row {line}: empty, duplicate or too-long 'MatchID'")
            
            if any(not n or len(n) > 100 for n in names) or len({name_key(n) for n in names}) != 4:
                raise DomainError(f"Row {line}: four different non-empty player names are required")
            
            try: a, b = int(row["Team1Score"]), int(row["Team2Score"]) # get team scores
            except ValueError: raise DomainError(f"Row {line}: invalid scores")
            if not valid_score(a, b): raise DomainError(f"Row {line}: invalid finishing score of {a}-{b}")

            result.append({"match_id": match_id, "names": names, "scores": [a, b]}) # add to results list
            ids.add(match_id)
            
    except csv.Error as error: # generic catch-all error
        raise DomainError(f"Invalid CSV: {error}")
    
    if not result: raise DomainError("CSV must contain at least one match")
    
    return result

def validate_week(week: str) -> str:
    
    """
    Checks if a week string is in ISO format.
    
    Arguments
    ---------
    week: `str`
        The week to check for.

    Returns
    -------
    `week`.
    
    Raises
    ------
    `DomainError` if the week is invalid.
    """
    
    try: 
        
        d = date.fromisoformat(week)
        if d.isoformat() != week or d.weekday() != 0: raise ValueError
        
    except (ValueError, TypeError): raise DomainError("Week must be an ISO date, e.g. 2026-10-30")
    
    return week

def connected(matches: List[dict], ids: list) -> bool:
    
    """
    Checks connectivity among participating players, treating players as graph nodes.

    Arguments
    ---------
    matches : `List[dict]`
        The matches played.
    ids : `list`
        The player IDs.

    Returns
    -------
    `bool` if the group of players is connectedd.
    """
    
    if not ids: return True
    adjacency = defaultdict(set)
    
    for m in matches:
        
        group = [m[f"player{i}"] for i in range(1, 5)]
        for p in group: adjacency[p].update(group)
    
    seen, stack = set(), [ids[0]]
    
    while stack:
        
        p = stack.pop()
        
        if p not in seen:
        
            seen.add(p)
            stack.extend(adjacency[p] - seen)
    
    return set(ids) <= seen

class Store:
    
    """
    Database operations manager.
    
    Attributes
    ----------
    path : `str`
        The path to the SQLite database.

    Methods
    -------
    `__init__(self, path)`
        Creates the `Store` instance and prepares the database.
    `connection(self, write = False)`
        Manages one database transaction.
    `create_player(self, name)`
        Registers a player under `name`.
    `_players(db)`
        Retrieves all registered players.
    `_digest(rows)`
        Creates a SHA-256 fingerprint of an upload.
    `import_week(self, week, txt, preview = False, replace = False)`
        Imports an entire week to the database.
    `_apply(self, db, week, text, digest, rows, replace)`
        Performs import mutations.
    `_rerate(self, db)`
        Recalculates all weeks from `1000` and sets the default for future imports.
    `_rebuild(self, db)`
        Rating function which processes weeks chronologically.
    `_week_ratings(db, week)`
        Retrieve one week's rating snapshots and new players.
    `weeks(self)`
        Returns all imported weeks.
    `leaderboard(self, week = None)`
        Builds a leaderboard of current or historical standings.
    `history(self, player_id)`
        Retrieves a player ID, initial rating, and weekly snapshots
    `matches(self, week, limit = None, limit = 100, offset = 0)`
        Returns matches together with calculation records.
    `insights(week = None)`
        Combines standings and matches into weekly insights (weekly gain, upsets, partnerships, oppositions)
    `backup(destination)`
        Creates a copy of the database at some location.
    """
    
    def __init__(self, path: str):
        
        self.path = str(Path(path).resolve())
        Path(self.path).parent.mkdir(parents = True, exist_ok = True)
        
        with closing(sqlite3.connect(self.path, timeout = 30, isolation_level = None)) as db:
            
            # enable WAL mode, foreign keys, create missing tables
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA foreign_keys=ON")
            
            db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA) # use schema.txt
            
            db.commit()
            
    @contextmanager
    def connection(self, write = False):
        
        """
        Manages one database transaction.
        
        Arguments
        ---------
        write : `bool`
            Whether `IMMEDIATE` should be used or not.
            
        Raises
        ------
        `BaseException` if there is some error with writing a transaction.
        """
        
        db = sqlite3.connect(self.path, timeout = 30, isolation_level = None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        
        try:
            
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        
        except BaseException: 
            
            db.rollback()
            raise
            
        finally: db.close()
    
    def create_player(self, name: str) -> dict:
        
        """
        Registers a player under `name`.
        
        Arguments
        ---------
        name : `str`
            The name of the player.
            
        Returns
        -------
        `dict` of player information.
            
        Raises
        ------
        `DomainError` if the player is already registered.
        """
        
        if not name_key(name) or len(name) > 100: raise DomainError("Invalid name")
        
        with self.connection(True) as db:
            
            key = name_key(name)
            
            if db.execute("SELECT 1 FROM Players WHERE name_key=?", (key,)).fetchone(): # already exists
                raise DomainError("Player already registered",  400)

            latest = db.execute("SELECT COALESCE(MAX(week),'') FROM Weeks").fetchone()[0]
            player_id = str(uuid.uuid4())
            
            db.execute("INSERT INTO Players(player_id,name,name_key,joined_after_week) VALUES(?,?,?,?)",
                       (player_id, " ".join(name.split()), key, latest))
            
            return dict(db.execute("SELECT * FROM Players WHERE player_id=?", (player_id,)).fetchone())
    
    @staticmethod
    def _players(db): return [dict(p) for p in db.execute("SELECT * FROM Players ORDER BY name_key")]
    
    def players(self):
        
        """
        Retrieves all registered players.
        A public wrapper of `_players`.
        
        Arguments
        ---------
        `None`.
            
        Returns
        -------
        `List[dict]` of player information.
        """
        
        with self.connection() as db: return self._players(db)
        
    @staticmethod
    def _digest(rows: List[dict]) -> object:
        
        """
        Creates a SHA-256 fingerprint of an upload.
        
        Arguments
        ---------
        rows : `List[dict]`
            The rows in a CSV upload.

        Returns
        -------
        `HASH` of upload.
        """
        
        canonical = []
        
        for row in rows:
            p, s = row["players"], row["scores"]
            teams = sorted([(sorted(p[:2]), s[0]), (sorted(p[2:]), s[1])])
            canonical.append([row["match_id"], teams])
        
        return hashlib.sha256(json.dumps(sorted(canonical), ensure_ascii = False).encode()).hexdigest()
    
    def import_week(self, week: str, text: str, *, preview = False, replace = False) -> dict:
        
        """
        Imports an entire week to the database.
        
        Arguments
        ---------
        week : `str`
            The week date as ISO.
        text : `str`
            The CSV text for the week.
        preview : `bool`
            Whether we are previewing results for the week.
        replace : `bool`
            Whether we are replacing an exisitng week.
            
        Returns
        -------
        `List[dict]` of week information.
        
        Raises
        ------
        `DomainError` for invalid weeks.
        """
        
        validate_week(week)
        
        rows = parse_csv(text)
        
        with self.connection(write = not preview) as db:
            
            players = self._players(db)
            by_name = {p["name_key"]: p for p in players}
            
            unknown = sorted({n for r in rows for n in r["names"] if name_key(n) not in by_name})
            if unknown: raise DomainError("Register these players first: " + ", ".join(unknown))
            
            for r in rows:
                
                selected = [by_name[name_key(n)] for n in r["names"]]
                
                if any(p["joined_after_week"] >= week for p in selected):
                    raise DomainError("A player was registered after this week - historical imports cannot include them")
                
                r["players"] = [p["player_id"] for p in selected]
            
            digest = self._digest(rows)
            
            existing = db.execute("SELECT * FROM Weeks WHERE week=?", (week,)).fetchone()
            
            if existing and existing["digest"] == digest: # already imported week
                return {"week": week, "status": "already_imported", "ratings": self._week_ratings(db, week)}
            
            if existing and not replace: # already imported week, different results
                raise DomainError("Week already exists with different results: use PUT to replace the complete week", 409)
            
            if replace and not existing: # trying to replace a new week
                raise DomainError("Cannot replace a week that does not exist", 404)
            
            latest = db.execute("SELECT MAX(week) FROM Weeks").fetchone()[0]
            
            if not existing and latest and week <= latest: # trying to add a week in wrong order
                raise DomainError("New weeks must be imported in chronological order", 409)
            
            for r in rows:
                
                used = db.execute("SELECT week FROM Matches WHERE match_id=?", (r["match_id"],)).fetchone()
                
                if used and used["week"] != week: # trying to add a week with a MatchID already existing
                    raise DomainError(f"MatchID {r['match_id']} already exists in week {used['week']}", 409)
            
            if preview:
                
                # simulate on in-memory database
                sim = sqlite3.connect(":memory:", isolation_level = None)
                sim.row_factory = sqlite3.Row
                
                try:
                    
                    db.backup(sim)
                    result = self._apply(sim, week, text, digest, rows, bool(existing)) # commit
                    result["status"] = "preview"
                    
                    return result
                
                finally: sim.close()
            
            return self._apply(db, week, text, digest, rows, bool(existing)) # commit
    
    def _apply(self, db, week: str, text: str, digest: object, rows: List[dict], replace: bool) -> dict:
        
        """
        Performs import mutations to add a week.
        
        Arguments
        ---------
        db : `...`
            The database connection.
        week : `str`
            The week date as ISO.
        text : `str`
            The CSV text for the week.
        digest : `object`
            The SHA256 hash for this week.
        rows : `List[dict]`
            A list of each entry with information.
        replace : `bool`
            Whether we are replacing an exisitng week.
            
        Returns
        -------
        `List[dict]` of player information.
        """
        
        if replace: # replace an old week
            db.execute("DELETE FROM Matches WHERE week=?", (week,))
            db.execute("UPDATE Weeks SET digest=?,source_csv=?,updated_at=CURRENT_TIMESTAMP WHERE week=?", (digest, text, week))
            
        else: db.execute("INSERT INTO Weeks(week,digest,source_csv,k) VALUES(?,?,?,?)", (week, digest, text, K)) # add a new week
            
        db.executemany("INSERT INTO Matches VALUES(?,?,?,?,?,?,?,?)", [(r["match_id"], week, *r["players"], *r["scores"]) for r in rows]) # update matches and rebuild db
        self._rebuild(db)
        
        affected = [r[0] for r in db.execute("SELECT week FROM Weeks WHERE week>=? ORDER BY week", (week,))]
        
        return {"week": week, "status": "replaced" if replace else "imported", "recalculated_weeks": affected, "ratings": self._week_ratings(db, week)}
    
    def _rerate(self, db) -> dict:
        
        before = {(r["week"], r["player_id"]): r["end_rating"] for r in db.execute("SELECT * FROM Ratings")}
        
        db.execute("UPDATE Weeks SET updated_at=CURRENT_TIMESTAMP")
        
        self._rebuild(db)
        
        changes = []
        
        for r in db.execute("SELECT r.*,p.name FROM Ratings r JOIN Players p USING(player_id) ORDER BY week,p.name_key"):
        
            old = before.get((r["week"], r["player_id"]), START_ELO)
            
            changes.append({"week": r["week"], "player_id": r["player_id"], "name": r["name"],
                            "old_rating": old, "new_rating": r["end_rating"],
                            "difference": r["end_rating"] - old})
        
        return {"status": "recalculated", "changes": changes}

    def rerate(self, *, preview = False) -> dict:
        
        """
        Recalculates all weeks from `1000` and sets the default for future imports.
        A public wrapper of `_rerate`.
        
        Arguments
        ---------
        preview : `bool`
            Whether we are previewing results for the week.
            
        Returns
        -------
        `dict` of recalculation information.
        """
        
        with self.connection(write = not preview) as db:
            
            if preview:
                
                sim = sqlite3.connect(":memory:", isolation_level=None)
                sim.row_factory = sqlite3.Row
                
                try:
                    
                    db.backup(sim)
                    result = self._rerate(sim)
                    result["status"] = "preview"
                    return result

                finally: sim.close()

        return self._rerate(db)

    def _rebuild(self, db):
        
        """
        Rating function which processes weeks chronologically.
        
        Arguments
        ---------
        db : `...`
            The database connection.
            
        Returns
        -------
        `None`
        """
         
        db.execute("DELETE FROM Ratings")
        db.execute("DELETE FROM MatchCalculations")

        ratings = {}
        players = self._players(db)

        for w in db.execute("SELECT * FROM Weeks ORDER BY week").fetchall():

            # get all joined players
            eligible = [p for p in players if p["joined_after_week"] < w["week"]]
            for p in eligible: ratings.setdefault(p["player_id"], START_ELO)
            
            starts = ratings.copy()
            changes = defaultdict(list)
            
            stats = {p["player_id"]: [0, 0, 0, 0, 0] for p in eligible}
            
            for m in db.execute("SELECT * FROM Matches WHERE week=? ORDER BY match_id", (w["week"],)):
                
                ids = [m[f"player{i}"] for i in range(1, 5)] # player IDs
                a, b = m["team1_score"], m["team2_score"] # team scores
                
                t1 = (starts[ids[0]] + starts[ids[1]]) / 2 # team 1 rating avg
                t2 = (starts[ids[2]] + starts[ids[3]]) / 2 # team 2 rating avg
                
                e = expected(t1, t2) # expected win prob. of first team
                actual = int(a > b) # 0 or 1 dependent on second or first winning
                
                raw_delta = w["k"] * (actual - e) # raw change in ELO

                multiplier = margin_multiplier(a, b) # margin multiplier
                delta = raw_delta * multiplier

                db.execute("INSERT INTO MatchCalculations VALUES(?,?,?,?,?,?,?,?)", (m["match_id"], t1, t2, e, actual, delta, raw_delta, multiplier))
                
                for i, pid in enumerate(ids):
                    
                    own, other = (a, b) if i < 2 else (b, a)
                    changes[pid].append(delta if i < 2 else -delta)
                    s = stats[pid]
                    
                    s[0] += 1
                    s[1] += int(own > other)
                    s[2] += int(own < other)
                    s[3] += own
                    s[4] += other
                    
            for pid, s in stats.items():
                
                delta = math.fsum(changes[pid])
                ratings[pid] = starts[pid] + delta
                db.execute("INSERT INTO Ratings VALUES(?,?,?,?,?,?,?,?,?,?)", (w["week"], pid, starts[pid], ratings[pid], delta, *s))

    @staticmethod
    def _week_ratings(db, week: str) -> List[dict]:
        
        """
        Retrieve one week's rating snapshots and new players.
        
        Arguments
        ---------
        db : `...`
            The database connection.
        week : `str`
            The week to obtain.
            
        Returns
        -------
        `List[dict]` of week rating information.
        """
        
        return [dict(r) for r in db.execute(
            "SELECT r.*,p.name FROM Ratings r JOIN Players p USING(player_id) WHERE week=? "
            "ORDER BY end_rating DESC,p.name_key", (week,))]
        
    def weeks(self):
        
        """
        Returns all imported weeks.
            
        Arguments
        ---------
        `None`

        Returns
        -------
        `List[dict]` of week rating information.
        """
        
        with self.connection() as db:
            
            return [dict(r) for r in db.execute(
                "SELECT w.week,w.k,w.created_at,w.updated_at,COUNT(m.match_id) AS matches "
                "FROM Weeks w LEFT JOIN Matches m USING(week) GROUP BY w.week ORDER BY w.week")]
            
    def leaderboard(self, week: Optional[str] = None):
        
        """
        Builds a leaderboard of current or historical standings.
            
        Arguments
        ---------
        week : `str`
            The week to obtain.
            
        Returns
        -------
        `List[dict]` of week rating information.
        
        Raises
        ------
        `DomainError` for invalid weeks.
        """
        
        with self.connection() as db:
            
            if week: # player info already exists
                
                validate_week(week)
                
                if not db.execute("SELECT 1 FROM Weeks WHERE week=?", (week,)).fetchone(): raise DomainError("Week not found", 404)
                rows = self._week_ratings(db, week)   
            
            else:
                
                rows = []
                
                # build leaderboard rows
                for p in self._players(db):
                    
                    last = db.execute("SELECT * FROM Ratings WHERE player_id=? ORDER BY week DESC LIMIT 1", (p["player_id"],)).fetchone()
                    
                    if last: rows.append({**dict(last), "name": p["name"]})
                    
                    else: rows.append({"player_id": p["player_id"], "name": p["name"], "week": None,
                                       "start_rating": START_ELO, "end_rating": START_ELO, "delta": 0,
                                       "games": 0, "wins": 0, "losses": 0, "points_for": 0, "points_against": 0})  

                    rows.sort(key = lambda r: (-r["end_rating"], name_key(r["name"])))
                
            previous = None
            rank = 0
                
            for index, r in enumerate(rows, 1):
                
                if previous is None or not math.isclose(r["end_rating"], previous, abs_tol = 1e-9, rel_tol = 0): rank = index
                previous = r["end_rating"]
                
                r["rank"] = rank
                r["total_games"] = db.execute("SELECT COALESCE(SUM(games),0) FROM Ratings WHERE player_id=? AND week<=?", (r["player_id"], week or "9999-12-31")).fetchone()[0]
                r["provisional"] = r["total_games"] < 20

            return rows
            
    def history(self, player_id: str) -> dict:
        
        """
        Retrieves a player ID, initial rating, and weekly snapshots.
        
        Arguments
        ---------
        player_id : `str`
            The player to obtain by ID.
            
        Returns
        -------
        `dict` of player history.
        
        Raises
        ------
        `DomainError` if the player doesn't exist.  
        """
        
        with self.connection() as db:
            
            p = db.execute("SELECT * FROM Players WHERE player_id=?", (player_id,)).fetchone()
            if not p: raise DomainError("Player not found", 404)            
            
            return {"player": dict(p), "initial_rating": START_ELO, "history": [dict(r) for r in db.execute("SELECT * FROM Ratings WHERE player_id=? ORDER BY week", (player_id,))]}

    def matches(self, week: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[dict]:
    
        """
        Returns matches together with calculation records.
        
        Arguments
        ---------
        week : `str`
            The week to obtain, if any.
            
        Returns
        -------
        `List[dict]` of match information.
        
        Raises
        ------
        `DomainError` for invalid weeks.
        """
        
        with self.connection() as db:
            
            if week: validate_week(week)
            
            rows = db.execute("SELECT m.*,c.team1_rating,c.team2_rating,c.expected_team1,"
                              "c.actual_team1,c.delta_per_team1_player,c.raw_delta_per_team1_player,c.margin_multiplier FROM Matches m "
                              "JOIN MatchCalculations c USING(match_id) "
                              "WHERE (? IS NULL OR week=?) ORDER BY week,match_id LIMIT ? OFFSET ?",
                              (week, week, limit, offset))
            
            # get player names
            names = {p["player_id"]: p["name"] for p in self._players(db)}

            return [{**dict(r), "team1_names": [names[r["player1"]], names[r["player2"]]], "team2_names": [names[r["player3"]], names[r["player4"]]]} for r in rows]
    
    def insights(self, week: Optional[str] = None) -> dict:
        
        """
        Combines standings and matches into weekly insights (weekly gain, upsets, partnerships, oppositions)
        
        Arguments
        ---------
        week : `str`
            The week to obtain.
            
        Returns
        -------
        `dict` of insight information.
        
        Raises
        ------
        `DomainError` for invalid weeks.
        """
        
        rows = self.leaderboard(week)
        games = self.matches(week, limit=10000)
        previous_weeks = [w["week"] for w in self.weeks() if w["week"] < week]
        
        if previous_weeks: previous = {r["player_id"]: r for r in self.leaderboard(previous_weeks[-1])}
        else: previous = {r["player_id"]: {"rank": 1} for r in rows}
        
        for r in rows:
            
            old = previous.get(r["player_id"])
            r["previous_rank"] = old["rank"] if old else None
            r["rank_change"] = old["rank"] - r["rank"] if old else None
            
        played = [r for r in rows if r["games"]]
        partners, opponents = defaultdict(list), defaultdict(list)
        
        for m in games:
            
            sides = [[m["player1"], m["player2"]], [m["player3"], m["player4"]]] # each team
            
            for side, (a, b) in enumerate(sides):
                win = int((m["team1_score"] > m["team2_score"]) == (side == 0))
                partners[tuple(sorted((a, b)))].append(win)
                
            for a in sides[0]:
                for b in sides[1]:
                    opponents[tuple(sorted((a, b)))].append(1) # sort opponents

        names = {r["player_id"]: r["name"] for r in rows}
            
        return {"week": week, "matches": len(games), "active_players": len(played),
                "rating_changes": sorted(played, key = lambda r: -r["delta"]),
                "upsets": sorted([m for m in games if  (m["expected_team1"] < .5 and m["actual_team1"] == 1)
                                or (m["expected_team1"] > .5 and m["actual_team1"] == 0)],
                                key = lambda m: min(m["expected_team1"], 1 - m["expected_team1"])),
                "partnerships": [{"players": list(pair), "names": [names[p] for p in pair],
                                "games": len(wins), "wins": sum(wins)} for pair, wins in sorted(partners.items())],
                "opponent_counts": [{"players": list(pair), "games": len(values)} for pair, values in sorted(opponents.items())],
                "schedule_connected": connected(games, [p["player_id"] for p in played])}
    
    def backup(self, destination: str):
        
        """
        Creates a copy of the database at some location.
        
        Arguments
        ---------
        destination : `str`
            The destination to backup.
            
        Raises
        ------
        `DomainError` if there are issues with backup.    
        """
        
        target = Path(destination).resolve()
        
        if target == Path(self.path): raise DomainError("Backup destination must difer from live database path")
        if target.exists(): raise DomainError("Backup destination already exists")
        
        target.parent.mkdir(parents = True, exist_ok = True)
        
        with self.connection() as db, sqlite3.connect(target) as out: db.backup(out)
        
        

                    
                    
            

            
            
        
        
        
                    