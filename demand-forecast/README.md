# demand-forecast

Bandwidth needed per event for remote live sports productions, built from the event planning workbooks and modelled in NetworkX. It is meant as a shared reference for **demand and event planning**: what each event needs, where the circuits run tight, and when events stack up at the production hub.

Events are named generically (Live event 1–4 and the event week) and remotes as Remote 1–4, with no sport, league, team, venue or vendor names. **CT Prod Hub** is the production hub every remote feeds.

![Bandwidth needed per event](bandwidth_per_event.png)

## The week at a glance (11/8 – 11/14)

| Game day | Event | Remote | Carrier | EPL data | Bitfire HSIP | Streams up | Needed | Full build | HSIP used |
|---|---|---|---|--:|--:|--:|--:|--:|--:|
| Sun 11/8 | Live event 1 · Week 1 | Remote 1 | Lumen | 500 | 500 | 10 of 15 | **900** | 1,100 | 80% |
| Tue 11/10 | Live event 2 · Week 2 | Remote 2 | Lumen | 1,000 | 1,000 | 12 of 15 | **1,480** | 1,600 | 48% |
| Fri 11/13 | Live event 3 · Week 1 | Remote 3 | AT&T | 1,000 | 1,000 | 9 of 15 | **1,360** | 1,600 | 36% |
| Sat 11/14 | Live event 4 · Week 2 | Remote 4 | Frontier/Segra | 500 ¹ | 500 ¹ | 10 of 15 | **900** | 1,100 | 80% |

All figures in Mbps, venue → CT Prod Hub. ¹ 1G circuits, of which 500 Mbps is taken.

## Talking points for planning

- **Every event needs 900 – 1,480 Mbps** into the hub: the EPL data circuit plus 40 Mbps for each camera stream sent back.
- **Overlapping events set the real demand.** The transmission windows of Live events 3 and 4 overlap from Fri 11/13 10:00 to Sat 11/14 00:59 ET, putting **2,260 Mbps** on the hub at once (2,700 if both remotes lit every slot). The rest of the week peaks at 1,480.
- **A 500 Mbps HSIP holds 12 streams.** Live events 1 and 4 send 10 streams (400 Mbps, 80% of the circuit). Adding a third camera, or lighting all 15 remote TX slots (600 Mbps), would overrun it. A show that may grow past 12 streams should be ordered on a 1G HSIP.
- **1G HSIP leaves room.** Live events 2 and 3 use under half of theirs, so late camera adds there are safe.
- **Returns are small.** Two program returns per event, 80 Mbps back to the venue.
- **LiveU bonded cellular** (4 streams at three of the four events) is backup on the cellular network and is not counted in the fiber totals.
- **Clean up the workbooks before they go out.** Three of the four still carry rows copied from another event (another remote's port numbers or another venue on the spare slots), and three list one remote slot twice. See `workbook_flags.csv`.

![Concurrent demand into the CT Prod Hub](hub_timeline.png)

## How each event connects

One straight line per circuit and per stream: EPL data (blue), the Bitfire HSIP circuit (black), each 40 Mbps camera stream up (red), returns down (green), spare remote slots (dashed) and LiveU cellular (purple).

![Event transport paths](event_paths.png)

## Planning rules used

- A Bitfire stream is 40 Mbps.
- **Needed** = EPL data + assigned camera streams. **Full build** = EPL data + all 15 remote TX slots.
- A stream is assigned when the workbook gives it a camera or a service ID; the rest are spare slots on the remote (15 TX and 5 RX per remote). A slot listed twice counts once.
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

The event workbooks themselves are not in this repo. The model is a `MultiGraph` with, for each event, remote → carrier → CT Prod Hub (one edge per circuit and per stream on each hop) and remote → LiveU → CT Prod Hub. Every drawing uses straight lines, parallel circuits are offset side by side, and each run checks that no line crosses a node it doesn't end on.
