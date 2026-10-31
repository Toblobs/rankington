# src > charts.py // @toblobs // 31.10.26
# for (rankington)

import io
import threading

from .core import DomainError
from .__init__ import START_ELO

_LOCK = threading.Lock()

BACKGROUND = "#1a1a1e"
GRADIENT = [
    "#555891",
    "#79579b",
    "#a0529b",
    "#c54b90",
    "#e4467b",
    "#f94b60",
    "#ff554d",
    "#ff7800",
]


def history_chart(store, player_ids, image_format: str = "svg"):
    
    if image_format not in {"svg", "png"}: raise DomainError("Format must be .svg or .png")
    if not player_ids or len(player_ids) > 24 or len(set(player_ids)) != len(player_ids): raise DomainError("Select 1 - 24 distinct player IDs")
    
    histories = [store.history(pid) for pid in player_ids]
    weeks = [w["week"] for w in store.weeks()]
    
    with _LOCK:
        
        from matplotlib.colors import LinearSegmentedColormap
        from matplotlib.figure import Figure
        
        count = len(histories)
        colour_map = LinearSegmentedColormap.from_list("rankington", GRADIENT, N = max(2, count))
        colours = [colour_map(i / max(1, count - 1)) for i in range(count)]
        
        width = max(10, min(24, 1.2 * (len(weeks) + 1)))
        
        figure = Figure(figsize = (width, 5.5), layout = "constrained", facecolor = BACKGROUND)
        ax = figure.subplots()
        ax.set_facecolor(BACKGROUND)
        
        end_labels = []
        
        for index, item in enumerate(histories):
            
            values = {r["week"]: r["end_rating"] for r in item["history"]}
            eligible = [i for i, w in enumerate(weeks, 1) if w > item["player"]["joined_after_week"]]
            
            style = {
                "color": colours[index],
                "marker": "s",
                "linestyle": "-",
                "linewidth": 2,
                "markersize": 6,
                "label": item["player"]["name"],
            }

            if not eligible:
                
                ax.plot([len(weeks)], [START_ELO], **style)
                end_labels.append((len(weeks), START_ELO, item["player"]["name"], colours[index]))
                
                continue
            
            start = eligible[0] - 1
            ax.plot([start, *eligible], [START_ELO, *[values[weeks[i - 1]] for i in eligible]], **style)

            end_labels.append((eligible[-1], values[weeks[eligible[-1] - 1]], item["player"]["name"], colours[index]))
        
        # horizontal dates
        tick_step = max(1, (len(weeks) + 11) // 12)
        tick_positions = sorted({0, *range(tick_step, len(weeks) + 1, tick_step), len(weeks)})
        tick_labels = ["Start" if position == 0 else weeks[position - 1] for position in tick_positions]

        ax.set_xticks(tick_positions, tick_labels, rotation = 0, ha = "center")
        
        # graph customisation
        ax.set_xlabel("Week", color = "white")
        ax.set_ylabel("Elo rating", color = "white")
        ax.set_title("Rankington", color = "white", pad = 14)
        
        ax.tick_params(axis = "both", colors = "white")
        ax.xaxis.get_offset_text().set_color("white")
        ax.yaxis.get_offset_text().set_color("white")
        
        ax.set_axisbelow(True)
        ax.grid(axis = "both", linestyle = "--", alpha = 0.2, color = "white")
        ax.axhline(START_ELO, color = "white", linestyle = "-", linewidth = 1, alpha = 1, zorder = 0)
        ax.axvline(tick_positions[0], color = "white", linestyle = "-", linewidth = 1, alpha = 1, zorder = 1)
        
        for spine in ax.spines.values(): spine.set_color("white")

        ax.legend(fontsize = 8, ncols = 2 if count <= 12 else 3, labelcolor = "white", loc = "upper left",
                  bbox_to_anchor = (0, 1), bbox_transform = ax.get_xaxis_transform(), borderaxespad = 0.8, borderpad = 0.8,
                  frameon = True, facecolor = BACKGROUND, edgecolor = "white", framealpha = 1, fancybox = False)

        # space names
        label_x = len(weeks) + 0.15
        ax.set_xlim(-0.05, len(weeks) + 0.35)
        figure.set_dpi(150)
        figure.canvas.draw()

        gap_points = 13
        gap_pixels = gap_points * figure.dpi / 72
        edge_padding = 8 * figure.dpi / 72

        labels = sorted(end_labels, key = lambda item: item[1])

        bottom = ax.bbox.y0 + edge_padding
        top = ax.bbox.y1 - edge_padding

        if len(labels) > 1: gap_pixels = min(gap_pixels, (top - bottom) / (len(labels) - 1))
        
        positions = []
        
        # push up if overlap
        for _, rating, _, _ in labels:
            desired_y = ax.transData.transform((0, rating))[1]
            minimum_y = (bottom if not positions else positions[-1] + gap_pixels)
            positions.append(max(desired_y, minimum_y))

        # push down from top
        if positions and positions[-1] > top:
            positions[-1] = top
            for i in range(len(positions) - 2, -1, -1): positions[i] = min(positions[i], positions[i + 1] - gap_pixels)

        # freeze before adding
        figure.set_layout_engine("none")
        inverse_transform = ax.transData.inverted()

        for (last_x, rating, name, colour), pixel_y in zip(labels, positions):
            
            label_y = inverse_transform.transform((ax.bbox.x0, pixel_y))[1]
            ax.annotate(name, xy = (last_x, rating), xytext = (label_x, label_y), textcoords = "data", color = "white", fontsize = 9, va = "center", ha = "left", 
                        annotation_clip = False, arrowprops = {"arrowstyle": "-", "color": colour, "linewidth": 0.8, "alpha": 0.7, "shrinkA": 3,  "shrinkB": 4})
            
        data = io.BytesIO()
        
        figure.savefig(
            data,
            format = image_format,
            dpi = 150,
            facecolor = BACKGROUND,
            transparent = False,
        )
        
        return data.getvalue()