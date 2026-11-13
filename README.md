# network-graphs

NetworkX network models and graphics. Each model lives in its own folder with
its own README.

| Model | Description |
|---|---|
| [demand-forecast](demand-forecast/) | Event demand forecast: bandwidth needed per live event, concurrent demand into the production hub and one-line-per-stream transport paths for ten remote productions (carriers and channels named generically) |
| [backbone5](backbone5/) | Backbone1 core + edges with estimated per-link latency |
| [lowlatency-plan1](lowlatency-plan1/) | Low Latency Prem-to-Cloud Plan1: 10-site backbone with AWS and Internet on-ramps, one line per circuit, NJ Metro and London region boxes, per-circuit one-way latency on diverse paths, a KMZ of every path and path maps |
| [lowlatency-plan2](lowlatency-plan2/) | Low Latency Prem-to-Cloud Plan2: Plan1 footprint plus ASH as a second hub (11 sites), AWS and Internet on-ramps, one line per circuit, NJ Metro and London region boxes, per-circuit one-way latency on diverse paths |
