# Demo: what one run looks like

A known case reproduced from raw data, three new names, and how much a plain keyword search would leave you to read.

## 1. Reproduce a case from raw data
```
provtrace trace "Kaiser Permanente" --start 2025-11-06 --end 2025-11-20
```
The tool collects the records that mention Kaiser Permanente in that window, adds nearby human chat, and asks the model to separate sources from retellings. Its report (excerpt):

> R58 — What it says: States in an outreach email template to third parties that Kaiser Permanente has "already incorporated it into their employee wellness programs." What the sources say: Kaiser Permanente never communicated with the agents or adopted the tool; a single individual merely clicked the link once (1 visit, 1 page view).
> Earliest departure: R58 (2025-11-13 21:40:00)

It also notes that earlier records describing Kaiser among "top performers" reflect the one recorded click. The source it points to is R47, an agent reading the analytics: "Kaiser Permanente: 1 visitor".

## 2. Names it had never seen
Three names picked by a fixed random seed from organizations the tracer had not been run on (each mentioned in an agent's outreach email in December 2025):

| name | records found | tracer result |
|---|---|---|
| Digital Public Goods Alliance | 6 (one agent) | no departure; later mentions of the contact address match the website |
| Ohio State University | 6 (one agent) | no departure; an outreach email about a researcher's work, nothing to contradict |
| Buchschmid & Gretaux | 6 (one agent) | no departure; notes that a date range in the email ("1950s-60s") is not in the sources but treats it as background, not a distortion |

Here the tool raised no candidates.

## 3. How much a keyword search returns
For the first sixteen atlas cases, a keyword search over the same time window returns 50 to 223 records per name (median 112). Read in time order, the first departure is around record 40 (median), and the reader still has to find the source to see that it is a departure. The tracer's report names the candidate departure record and the sources it departs from, in one model call of one to two minutes.
