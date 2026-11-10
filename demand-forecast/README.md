# demand-forecast

Bandwidth needed per event for remote college-basketball productions, built from the event planning workbooks and modelled in NetworkX. It is meant as a shared reference for **demand and event planning**: what each event needs, where the circuits run tight, and when events stack up at the production hub.

Events are named by type (men's or women's college basketball, conference, week), not by teams or venues. **CT Prod Hub** is the production hub every truck feeds.

![Bandwidth needed per event](bandwidth_per_event.png)

## The week at a glance (11/8 – 11/14)

| Game day | Event | Truck | Carrier | EPL data | Bitfire HSIP | Streams up | Needed | Full build | HSIP used |
|---|---|---|---|--:|--:|--:|--:|--:|--:|
| Sun 11/8 | MCBB Big East · Week 1 | GCV Apollo | Lumen | 500 | 500 | 10 of 15 | **900** | 1,100 | 80% |
| Tue 11/10 | MCBB Big 12 · Week 2 | GCV Gemini | Lumen | 1,000 | 1,000 | 12 of 15 | **1,480** | 1,600 | 48% |
| Fri 11/13 | MCBB B1G · Week 1 | LMG MU-5 | AT&T | 1,000 | 1,000 | 9 of 15 | **1,360** | 1,600 | 36% |
| Sat 11/14 | WCBB Big East · Week 2 | GCV Webby | Frontier/Segra | 500 ¹ | 500 ¹ | 10 of 15 | **900** | 1,100 | 80% |

All figures in Mbps, venue → CT Prod Hub. ¹ 1G circuits, of which 500 Mbps is taken.

## Talking points for planning

- **Every event needs 900 – 1,480 Mbps** into the hub: the EPL data circuit plus 40 Mbps for each camera stream sent back.
- **Overlapping events set the real demand.** The B1G and WCBB Big East transmission windows overlap from Fri 11/13 10:00 to Sat 11/14 00:59 ET, putting **2,260 Mbps** on the hub at once (2,700 if both trucks lit every slot). The rest of the week peaks at 1,480.
- **A 500 Mbps HSIP holds 12 streams.** Both Big East events send 10 streams (400 Mbps, 80% of the circuit). Adding a third camera, or lighting all 15 truck slots (600 Mbps), would overrun it. A show that may grow past 12 streams should be ordered on a 1G HSIP.
- **1G HSIP leaves room.** The Big 12 and B1G events use under half of theirs, so late camera adds there are safe.
- **Returns are small.** Two program returns per event, 80 Mbps back to the venue.
- **LiveU bonded cellular** (4 streams at three of the four events) is backup on the cellular network and is not counted in the fiber totals.
- **Clean up the workbooks before they go out.** Three of the four still carry rows copied from another event (another truck's port numbers or another venue on the spare slots), and three list one truck slot twice. See `workbook_flags.csv`.

![Concurrent demand into the CT Prod Hub](hub_timeline.png)

## How each event connects

One straight line per circuit and per stream: EPL data (blue), the Bitfire HSIP circuit (black), each 40 Mbps camera stream up (red), returns down (green), spare truck slots (dashed) and LiveU cellular (purple).

![Event transport paths](event_paths.png)

## Planning rules used

- A Bitfire stream is 40 Mbps.
- **Needed** = EPL data + assigned camera streams. **Full build** = EPL data + all 15 truck TX slots.
- A stream is assigned when the workbook gives it a camera or a service ID; the rest are spare slots on the truck (15 TX and 5 RX per truck). A slot listed twice counts once.
- Where a 1G circuit is marked as taking 500 Mbps, 500 is used.
- Concurrency uses each event's transmission window (ET).

## Files

| File | What it is |
|---|---|
| `demand_forecast_model.py` | Reads the event workbooks, builds the NetworkX model, writes everything below |
| `bandwidth_per_event.csv` | One row per event: circuits, streams, needed, full build, HSIP use, TX window |
| `workbook_flags.csv` | Workbook findings to fix before the event |
| `report.txt` | The same results as plain text |
| `bandwidth_per_event.png`, `event_paths.png`, `hub_timeline.png` | The drawings above |

## Run it on next week's workbooks

```bash
pip install networkx matplotlib openpyxl
python demand_forecast_model.py path/to/workbooks/*.xlsx --out .
```

The event workbooks themselves are not in this repo. The model is a `MultiGraph` with, for each event, truck → carrier → CT Prod Hub (one edge per circuit and per stream on each hop) and truck → LiveU → CT Prod Hub. Every drawing uses straight lines, parallel circuits are offset side by side, and each run checks that no line crosses a node it doesn't end on.
