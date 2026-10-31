# src > scheduling.py // @toblobs // 31.10.26
# for (rankington)

import itertools
import random
from collections import Counter
from functools import lru_cache

from .core import DomainError, expected

def schedule(store, player_ids: list, mode: str = "balanced", rounds = 12, seed = 0) -> dict:
    
    """
    Attempts to schedule matches for a future session.
    
    Arguments
    ---------
    store : `Store`
        The Store instance.
    player_ids : `list`
        List of players to schedule. Must be between `4` and `24`, and `% 4` for `round-robin`.
    mode : `str`
        The scheduling mode:
        - `round-robin` has every player partnering every other exactly once, always with (n - 1) rounds.
        - `balanced` is a greedy heuristic favouring close team ratings and fewer repeated parnters/opponents.
        - `matchmaking` works like `balanced` but also favours players with similar individual ratings.
    rounds : `int`
        The number of rounds, must be within `1` and `12`.
    seed : `int`
        The seed for the RNG, defaults `0`.
        
    Returns
    -------
    `dict` of scheduling information.
    
    Raises
    ------
    `DomainError` if there is an issue with scheduling.
    """
            
    if not 4 <= len(player_ids) <= 24 or len(set(player_ids)) != len(player_ids): raise DomainError("Select 4–24 distinct player IDs")
    if mode not in {"balanced", "matchmaking", "round-robin"}: raise DomainError("Unknown scheduling mode")
    if not 1 <= rounds <= 30: raise DomainError("Rounds must be between 1 and 30")
    
    board = {p["player_id"]: p for p in store.leaderboard()}
    if any(p not in board for p in player_ids): raise DomainError("Unknown player ID")
    
    rng = random.Random(seed) # set seed
    
    ids = sorted(player_ids)
    rng.shuffle(ids)
    
    ratings = {p: board[p]["end_rating"] for p in ids}
    partners, opponents, games = Counter(), Counter(), Counter()
    output = []
    
    def team_rating(team): return sum(ratings[p] for p in team) / 2
    
    def cost(a, b):
        
        balance = abs(team_rating(a) - team_rating(b)) / 100
        repeat = .4 * (partners[tuple(sorted(a))] + partners[tuple(sorted(b))])
        repeat += .05 * sum(opponents[tuple(sorted((p, q)))] for p in a for q in b)
        spread = (max(ratings[p] for p in a + b) - min(ratings[p] for p in a + b)) / 400
        return balance + repeat + (spread if mode == "matchmaking" else 0)
    
    def record(a, b):
        
        partners[tuple(sorted(a))] += 1
        partners[tuple(sorted(b))] += 1
        
        for p in a:
            for q in b:
                opponents[tuple(sorted((p, q)))] += 1
                
        for p in a + b: games[p] += 1
        
        return {"team1": list(a), "team2": list(b),
                "team1_names": [board[p]["name"] for p in a],
                "team2_names": [board[p]["name"] for p in b],
                "team1_rating": team_rating(a), "team2_rating": team_rating(b),
                "expected_team1": expected(team_rating(a), team_rating(b))}
    
    ## both modes may not be optimal
    
    # every player partners every other exactly once, always (n - 1) rounds
    if mode == "round-robin":
        
        if len(ids) % 4: raise DomainError("Complete partner round robin requires player count divisible by 4 - use balanced mode for byes")
        
        ring = ids[:]
        
        for number in range(len(ids) - 1):
                
            pairs = [tuple((ring[i], ring[- i - 1])) for i in range(len(ids) // 2)]
            
            # minimum cost pairing
            @lru_cache(None)
            def pair_up(remaining):
                
                if not remaining: return 0, ()
                a = remaining[0]
                options = []
                
                for b in remaining[1:]:
                    rest = tuple(i for i in remaining if i not in (a, b))
                    value, choices = pair_up(rest)
                    options.append((value + cost(pairs[a], pairs[b]), ((a, b),) + choices))
                    
                return min(options)
            
            _, choices = pair_up(tuple(range(len(pairs))))
            output.append({"round": number + 1, "matches": [record(pairs[a], pairs[b]) for a, b in choices], "byes": []})
            ring = [ring[0], ring[-1], *ring[1:-1]]
    
    # greedy heuristic favouring close team ratings and fewer repeated parnters/opponents
    # matchmaking mode also favours players with similar individual ratings
    else: 
        
        for number in range(rounds):
            
            # select participants first (to guarantee game-count difference <= 1)
            priority = {p: rng.random() for p in ids}
            active = sorted(ids, key = lambda p: (games[p], priority[p]))[:len(ids) // 4 * 4]
            remaining, matches = set(active), []
            
            while remaining:
                
                best = None
                
                for quartet in itertools.combinations(sorted(remaining), 4):
                    
                    a, b, c, d = quartet
                
                    for t1, t2 in [((a, b), (c, d)), ((a, c),(b, d)), ((a, d),(b, c))]:
                        
                        candidate = (cost(t1, t2), t1, t2)
                        if best is None or candidate < best: best = candidate
                        
                _, a, b = best # type: ignore
                
                
                matches.append(record(a, b))
                remaining.difference_update(a + b)
                
            output.append({"round": number+1, "matches": matches, "byes": [p for p in ids if p not in active]})
    
    return {"mode": mode, "seed": seed, "rounds": output,
            "games_per_player": {p: games[p] for p in ids},
            "partner_counts": [{"players": list(pair), "games": count} for pair, count in sorted(partners.items())],
            "opponent_counts": [{"players": list(pair), "games": count} for pair, count in sorted(opponents.items())]}

        
        
        