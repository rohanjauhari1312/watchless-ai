# WatchlessAI — Product Requirements Document

**Version:** 1.0  
**Date:** June 2026  
**Author:** Rohan Jauhari

---

## 1. Product Overview

### What it is

WatchlessAI is a conversational AI system that watches camera footage continuously and lets you ask questions about it in natural language. You point it at a video source — an RTSP stream or an uploaded file — and from that point forward you can ask:

- "Did anyone enter the room after 3pm?"
- "Which car was parked near the gate?"
- "How long did the child study?"
- "Was there anything suspicious in the last hour?"

It runs in the background, building a time-indexed log of everything it observes, and fires alerts automatically when conditions you define in plain English are met — without you watching the footage.

### What it is not

It is not a camera manufacturer, a video storage platform, or a traditional motion-detection system. It sits on top of existing camera infrastructure and adds an intelligence layer — search, alerting, and retrospective queries — that no camera vendor currently provides at SMB-accessible pricing.

### Core design constraints

- Under $1/camera/day in AI inference cost
- Zero login friction — no accounts, no passwords
- Bring your own camera — works with any RTSP stream or video file
- No hardware lock-in

---

## 2. Problem Statement

Security cameras generate hours of footage that nobody watches. Reviewing it is slow and tedious, and by the time you look, the moment has passed. When something does happen — a theft, a dispute, an incident — finding the relevant clip requires scrubbing through hours of recording manually.

Existing AI-enhanced camera systems (Verkada, Arlo, Nest) solve a narrow version of this: they detect preset categories (person, vehicle, package) and send motion clips. But they cannot answer retrospective questions, cannot accept custom alert conditions in natural language, and cannot reason about context across time. You cannot ask an Arlo camera "how long was the back door open?" or "did anyone go into the office after the last employee left?"

The gap is: **no product lets a non-technical user ask arbitrary natural language questions about their own footage, on their own cameras, at a price that makes sense for a small business or home.**

---

## 3. Goals and Non-Goals

### Goals

- Let any user ask a natural language question about footage and get a grounded, accurate answer
- Fire configurable alerts in real time when user-defined conditions are met
- Distinguish genuinely new alert-worthy events from ongoing situations already flagged (no alert spam)
- Validate AI-generated answers and alerts against a second independent agent before surfacing them
- Run on any camera with an RTSP URL or any video file upload
- Deploy publicly with no authentication required

### Non-Goals (v1)

- Live video streaming or playback in the UI
- Multi-user accounts or role-based access
- Mobile app
- On-device / edge inference
- Integration with specific camera brands' proprietary APIs
- Video export or clip generation

---

## 4. User Stories

| As a... | I want to... | So that... |
|---|---|---|
| Restaurant owner | Ask "was the register unattended after close?" | I can verify staff compliance without watching hours of footage |
| Property manager | Ask "was the front door propped open overnight?" | I can respond to tenant complaints with evidence |
| Home user | Set an alert for "suspicious person at front door" | I get notified only when something genuinely new happens |
| Warehouse operator | Ask "how long was loading dock 2 idle on Tuesday?" | I can identify operational bottlenecks |
| Any user | Upload a video file and start asking questions immediately | I can analyze existing footage without a live camera |
| Any user | Delete individual frames or clear all frames for a camera | I can manage storage and remove unwanted data |

---

## 5. Architecture

### System diagram

See [`docs/architecture.svg`](architecture.svg) for the full visual.

### Components

#### Ingestion layer

A background thread (one per camera) opens the video source with OpenCV (`cv2.VideoCapture`) — either RTSP or a file. Every N seconds (default 10) it grabs a frame, saves it as a JPEG, and passes it to the vision layer. Threads are tracked in a module-level dict and clean themselves up on exit.

#### Vision layer

Each saved JPEG is sent to Claude Haiku with a structured prompt requesting JSON output: a human-readable summary, a list of people with attributes and actions, a list of objects with positions and descriptions. This is a single fixed API call, not an agent.

#### Storage layer

SQLite via SQLAlchemy. Four tables:

- `cameras` — source URL/file path, name, active status
- `frames` — one row per sampled frame: camera_id, timestamp, image_path, summary, analysis_json
- `alerts` — user-defined conditions, active flag, is_agentic flag
- `alert_events` — when an alert fired: alert_id, frame_id, triggered_at, reason

A non-obvious production requirement: SQLite's default transaction handling serves stale data across threads. Fixed via SQLAlchemy event listeners that set `isolation_level = None` on connect and issue explicit `BEGIN` before each transaction.

#### Three agents

**Alert engine**

For alerts marked agentic, the agent calls `get_recent_frames` to understand what was happening before the current frame, calls `get_recent_alert_events` to check if it already fired for the same situation, then calls `submit_verdict` with its decision. This prevents alert spam when a person is still in frame doing the same thing — the agent only re-fires when something materially changes.

For simple (non-agentic) alerts, a single-shot prompt asks whether the current frame matches the condition.

**Chat agent**

Given a natural language question, the agent decides which tools to call (`search_frames` with keyword and time filters, `get_alert_history`), calls them in sequence until it has enough evidence, then synthesizes an answer. For duration questions it finds first and last timestamps where an activity holds; for identity questions among candidates it uses distinguishing attributes in the stored observations. Up to 5 tool iterations per question.

**Validation agent**

An independent second opinion that runs after the other two produce outputs. For alerts: re-examines the actual JPEG and confirms whether the proposed reason is plausible. For chat answers: checks whether the answer is supported by the tool evidence gathered. If it disagrees, the alert is suppressed or the chat agent gets one corrective retry with the validator's specific objection. Fails open — errors do not block the primary output.

#### Frontend

Vanilla JS single-page app, no framework, no build step. Four tabs:

- **Cameras** — add camera by RTSP URL or file upload, start/stop monitoring
- **Frames** — browsable log of sampled frames with thumbnails and summaries; per-frame delete and clear-all
- **Alerts** — define conditions in plain English, toggle agentic mode, view fired events
- **Ask** — chat interface with markdown-rendered responses

#### Backend

FastAPI with no authentication. All routes are open. Static directory mounted with `html=True` to serve the SPA at `/`.

#### Deployment

Railway, via `Procfile`. `opencv-python-headless` required (not `opencv-python`) because the standard package requires `libGL.so.1` which is absent in Railway's container. A Railway Volume at `/app/data` persists the SQLite database and saved frames across redeploys.

---

## 6. Market Sizing

### Top-down

The global video surveillance market is ~$55B in 2024 (hardware + software), growing at ~12% CAGR.

The relevant slice — **AI video analytics software** — is ~$8B today, growing at ~25% CAGR.

The directly addressable segment — **cloud-managed camera intelligence for SMBs and prosumers** — is estimated at ~$2.5B today.

### Bottom-up

~770 million surveillance cameras installed globally. ~70 million in the US.

Addressable pool (non-enterprise cameras where owners want to query footage, not just archive it): ~150 million cameras globally.

At $30/camera/month, **1% penetration = ~$540M ARR**. At 0.1% penetration = ~$54M ARR.

US SMB near-term TAM: ~15 million small businesses with at least one camera. If 5% would pay $15–30/month/camera for AI search: **$135M–$270M annual market**.

---

## 7. Competitor Analysis

### Direct — AI-native video intelligence

| Competitor | Positioning | Price | Gap WatchlessAI exploits |
|---|---|---|---|
| Verkada | Enterprise cloud cameras, AI built in | $2K–$15K/camera hardware + SaaS | Hardware lock-in, enterprise-only, no BYOC |
| Verkada Helix | Software-only for existing cameras | ~$1,200/camera/year | Enterprise pricing, not conversational |
| BriefCam | Video synopsis and search | $50K–$500K deployments | Completely inaccessible to SMBs |
| Genetec | VMS with analytics | Tens of thousands upfront | Requires IT staff, no natural language |
| Milestone XProtect | On-prem VMS + plugins | $300–$3K/camera | Complex setup, no conversational layer |

### Adjacent — consumer and prosumer smart cameras

| Competitor | Positioning | Price | Gap |
|---|---|---|---|
| Arlo | Consumer smart cameras, clip-based AI | $15–$20/month | Fixed alert categories only (person, vehicle, package) — no custom conditions, no retrospective queries |
| Google Nest | Consumer cameras, activity zones | $8–$15/month | Fixed detection, no NLP |
| Ring | Amazon ecosystem, motion clips | $10/month | No search, no natural language |
| Reolink | Budget cameras, basic AI | $15–$30 one-time | Minimal AI, no cloud intelligence |

### Adjacent — AI video analysis (not continuous)

| Competitor | Positioning | Gap |
|---|---|---|
| Twelve Labs | Video understanding API | Developer API, not an end-user product; pricing scales with video volume |
| AWS Rekognition Video | Cloud video ML primitives | Requires heavy integration; no out-of-box product |
| Ambient.ai | Workplace safety AI | Enterprise-only, proprietary hardware |

### The white space

No product currently combines all five of:

1. Bring your own camera (RTSP or file) — no hardware lock-in
2. Natural language retrospective queries spanning hours or days
3. Custom alert conditions in plain English, not preset categories
4. Agentic deduplication — no spam when the same situation persists
5. SMB/prosumer pricing under $30/camera/month

Every competitor owns 2–3 of these at most. WatchlessAI's defensible position is the combination.

---

## 8. Customer Segmentation

### Segment 1 — Small Business Owner (primary)

**Who:** Restaurant owners, retail managers, auto shops, salons. 1–8 cameras. No dedicated security staff.

**Pain:** Motion alerts that trigger on shadows. Reviewing footage after an incident takes hours. Can't verify whether a specific event happened without manual scrubbing.

**Jobs to be done:** "Did anyone go into the back office after 6pm?" "Was the register unattended?" "Did the delivery arrive?"

**Willingness to pay:** $20–$40/camera/month. Price-sensitive but will pay when it replaces 2+ hours of DVR scrubbing per incident.

**Acquisition:** Google Ads on "security camera AI alerts," local business Facebook groups, POS ISV partnerships (Square, Toast).

---

### Segment 2 — Property Manager

**Who:** Manages 5–50 residential units or commercial properties. Cameras at entrances, parking lots, amenity spaces.

**Pain:** Tenant disputes about what happened and when. Insurance claims requiring footage evidence. Staff accountability.

**Jobs to be done:** "Was the front door propped open between 2–4am?" "Did maintenance show up Thursday?" Time-indexed evidence without watching recordings.

**Willingness to pay:** $15–$25/camera/month. Bundle pricing per property (not per camera) may convert better.

**Acquisition:** Property management SaaS integrations (Buildium, AppFolio), landlord Facebook groups, direct outreach to PM companies.

---

### Segment 3 — Prosumer / Home Power User (early adopter)

**Who:** Tech-savvy homeowners with 3–10 cameras (Reolink, Amcrest, Hikvision). Already running Home Assistant or Frigate. Cameras already on RTSP.

**Pain:** Object detection without retrospective queries. "When did the kids get home?" requires scrubbing. Alert fatigue from generic motion detection.

**Jobs to be done:** Plug existing RTSP streams in, immediately get natural language search and custom English-language alerts. Zero hardware changes.

**Willingness to pay:** $10–$20/month total (not per camera — they have many cameras). Will evangelize heavily if it works well.

**Acquisition:** Reddit (r/homeassistant, r/homesecurity, r/surveillance), Home Assistant forums, YouTube reviews. This segment finds products; they don't get found via ads.

---

### Segment 4 — Warehouse / Logistics Operations

**Who:** Small-to-mid warehouses, fulfillment centers, manufacturing floors. 10–50 cameras. Existing VMS with no analytics.

**Pain:** Shrinkage investigation. Worker safety incident review. Shift accountability.

**Jobs to be done:** "Did the truck leave with a full load?" "How long was loading dock 2 idle?" Operational intelligence over existing camera infrastructure.

**Willingness to pay:** $30–$60/camera/month. Clear ROI framing (shrinkage recovered, labor compliance) justifies higher price.

**Acquisition:** Direct sales, warehouse operations consultants, WMS platform integrations.

---

### Prioritization

| Segment | Acquisition cost | Sales cycle | Revenue potential | Priority |
|---|---|---|---|---|
| Prosumer | Very low (organic) | Instant | Low per user, high volume | Ship first — stress-tests product |
| Small business | Low–medium | Days | Medium | Primary revenue target |
| Property manager | Medium | Weeks | Medium-high | Expansion after core is proven |
| Warehouse/logistics | High (direct sales) | Months | High per account | Later-stage |

---

## 9. Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Sparse sampling misses brief events (e.g. a 3-second action) | High | Medium | Make sampling interval configurable; document the tradeoff clearly |
| RTSP stream access blocked by network/firewall | High | Medium | Upload mode as fallback; document port requirements |
| OpenCV codec support varies by deployment environment | Medium | High | Use `opencv-python-headless`; test on target infra before shipping |
| SQLite write contention under high camera count | Medium | High | Migration path to PostgreSQL when camera count exceeds ~10 concurrent |
| Claude API cost spikes if sampling interval is too low | Medium | High | Hard floor on sampling interval (minimum 5s); cost calculator in onboarding |
| False positive alerts erode user trust | Medium | High | Validation agent + agentic deduplication already in place |
| Railway ephemeral filesystem loses data on redeploy | Low (mitigated) | Critical | Persistent Volume already configured at `/app/data` |

---

## 10. Success Metrics

| Metric | Target (90 days post-launch) |
|---|---|
| Cameras added by external users | 50+ |
| Chat questions answered | 500+ |
| Alert events fired | 200+ |
| User-reported false positive rate | < 15% |
| Average API cost per camera per day | < $1.00 |
| Time from camera add to first frame stored | < 2 minutes |

---

## 11. Open Questions

1. **Pricing model** — per camera/month vs. per query vs. flat monthly. Prosumers prefer flat; SMBs prefer per-camera so they can justify per-location.
2. **Retention policy** — how long should frames be kept? Storage grows unbounded currently. Options: rolling 30-day window, manual clear, tiered (thumbnails forever, JPEGs 30 days).
3. **Multi-camera queries** — "did anything happen on any camera after 10pm?" is not yet supported. Cross-camera chat is a natural next feature.
4. **Notifications** — alerts fire and are stored, but no push/email notification exists yet. Without outbound notification, users must check the app to see alert events.
5. **Mobile** — the SPA is not responsive. Property managers and business owners primarily check on phones.
