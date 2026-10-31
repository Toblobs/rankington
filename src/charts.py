# src > charts.py // @toblobs // 31.10.26
# for (rankington)

import io
import threading

from .core import DomainError
from .__init__ import START_ELO

_LOCK = threading.Lock()

def history_chart(store, player_ids, image_format: str = "svg"):
    
    if image_format not in {"svg", "png"}: raise DomainError("Format must be .svg or .png")
    if not player_ids or len(player_ids) > 24 or len(set(player_ids)) != len(player_ids): raise DomainError("Select 1 - 24 distinct player IDs")
    
    histories = [store.history(pid) for pid in player_ids]
    
    with _LOCK:
        
        from matplotlib.figure import Figure
        
        figure = Figure(figsize = (10, 5.5), layout = "constrained")
        ax = figure.subplots()
        
        weeks = [w["week"] for w in store.weeks()]
        
        for item in histories:
            
            values = {r["week"]: r["end_rating"] for r in item["history"]}
            eligible = [i for i, w in enumerate(weeks, 1) if w > item["player"]["joined_after_week"]]
            
            if not eligible:
                
                ax.plot([len(weeks)], [START_ELO], marker = "o", label = item["player"]["name"])
                continue
            
            start = eligible[0] - 1
            ax.plot([start, *eligible], [START_ELO, *[values[weeks[i - 1]] for i in eligible]], marker = "o", label = item["player"]["name"])
            
        ax.set_xticks(range(len(weeks) + 1), ["Start", *weeks], rotation = 35, ha = "right")
        
        ax.set_xlabel("Week")
        ax.set_ylabel("Elo rating")
        
        ax.set_title("Rankington")
        ax.axhline(START_ELO, color = "#888888", linewidth = 0.7, linestyle = "--")
        
        ax.grid(alpha = 0.2)
        ax.legend(loc = "best", fontsize = 8, ncols = 2)
        
        data = io.BytesIO()
        figure.savefig(data, format = image_format, dpi = 150)
        
        return data.getvalue()
