# RescueNYC — Architecture

Everything right of the laptop runs on the team's IBM LinuxONE Community Cloud VM (s390x).

```mermaid
flowchart LR
  subgraph Laptop["Team laptop (little-endian)"]
    OD["NYC Open Data<br/>76xm-jjuj FDNY EMS<br/>Incident Dispatch"] --> F["scripts/fetch_data.py<br/>incident rows, timestamps only"]
  end
  F -- "scp CSV (no pickles,<br/>no parquet)" --> C
  subgraph L1["IBM LinuxONE VM · s390x · L1CC ML image"]
    C["data.py<br/>clean · recompute durations<br/>validity bounds · audit"] --> R["stream.py replay engine<br/>call events in time order →<br/>unassigned backlog, held calls,<br/>units at hospital at each hour"]
    R --> FT["features.py<br/>leakage-safe features at T<br/>trailing 8-week label for T→T+1"]
    FT --> M["model.py<br/>xgboost + 4 baselines<br/>(demand-only, hour-of-week,<br/>persistence, backlog logistic)"]
    M --> EV["evaluation<br/>PR-AUC · onset recall · lead time<br/>false alerts/day · cascade test"]
    M --> API["FastAPI in a container<br/>/risk /replay /evaluation<br/>live scoring per request"]
    API --> B["briefing.py<br/>operator note + verifier<br/>(rejects unsupported numbers)"]
    M -. "warning model<br/>(trained on other weeks)" .-> DES
    C --> DES["des.py policy lab<br/>discrete-event fleet simulator<br/>real call arrivals · calibrated fleet<br/>handover shock · reserve policies"]
    DES --> LAB["/lab /lab/series<br/>paired experiments, 95% CI"]
    BENCH["/benchmark<br/>replay events/s · scoring p50/p99"] --- API
  end
  API --> UI["Dashboard (same origin)<br/>Early warning · replay<br/>Policy lab · two worlds"]
  LAB --> UI
  B --> UI
```

## Why each piece is where it is

| Choice | Reason |
|---|---|
| Train, score, replay and simulate on the VM | The AI/ML work judged under criterion 3 actually runs on LinuxONE; the dashboard shows `computed_on: s390x` from the live API |
| Only CSV crosses from laptop to VM; models saved as xgboost JSON | s390x is big-endian; pickles and some binary formats don't transfer safely |
| Packages from the L1CC ML image (pandas, scikit-learn, xgboost) | PyPI has no s390x wheels for pandas; no source builds during the event |
| One container, one port, dashboard served by the API | One team VM; port exposure may be limited (SSH tunnel fallback works the same) |
| Replay engine is the single source of backlog features | Batch training features and live scoring use the same code, so they cannot drift |
| Policy lab uses real arrivals but a SCENARIO fleet | Public data has no unit availability; fleet is calibrated to observed dispatch waits and labeled as an assumption |
| Only aggregates leave the VM; the briefing never sees row-level data | Privacy by architecture for 911-adjacent data |
