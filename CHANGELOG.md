# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-06-03

### Added
- **Multi-DB Support:** Intelligent routing between internal `benchmark_test.db` and external `market_intel.db`.
- **Semantic Cache:** Two-tier caching (Exact & Normalized) for sub-10ms response times.
- **Hyper-Real-Time Streaming:** Immediate query execution on spacebar with 350ms debounce.
- **AI Insights Layer:** Automated one-liner summaries and deep technical analysis for every query.
- **Advanced Reasoning:** Native support for mathematical comparisons (`<`, `>`, `=`) and exact date filtering (`YYYY-MM-DD`).
- **Expanded Dictionary:** Comprehensive synonyms for corporate and market metrics (revenue, expenditure, headcount, market share, etc.).
- **Improved Layout:** Optimized dashboard with better information hierarchy, relocated logic tags, and responsive chart scaling.
- **Unit Awareness:** System now distinguishes between monetary values (USD) and counts (Units).

### Fixed
- **Data Accuracy:** Resolved "broad sum" errors by implementing precise exact-date SQL filtering using `DATE()` and `strftime`.
- **UI Redundancy:** Removed repetitive labeling (e.g., "Total total headcount") in the results display.
- **Stability:** Fixed runtime crashes caused by unexpected AI response formats using a new "safety stringify" layer.
- **Fallback Logic:** Prevented silent ignoring of unknown query terms by enforcing strict fallback triggers.

### Changed
- **Default Model:** Switched AI fallback and analysis to `phi3.5:3.8b` for improved reasoning and instruction following.
- **SQL Generator:** Refactored for better handling of aggregations vs. breakdowns.
