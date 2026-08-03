# ADR-001: Modular monolith and integer-millisecond timebase

Status: accepted, 2026-08-03

## Context

CLI, API, Worker and Web need identical business behavior. Media boundaries cross JSON, SQLite, Pydantic, SRT and FFmpeg, where floating seconds can drift.

## Decision

Use a ports-and-adapters modular monolith with one application/service layer and composition root. Keep domain free of frameworks/adapters. Use integer milliseconds from source start for every stored/domain time; convert decimal seconds only at interfaces.

## Consequences

Entry points remain thin, Mock and real adapters share contracts, and revisions compare exactly. Adapter formatting must be covered for FFmpeg and SRT. We accept a small conversion layer instead of ambiguous float fields. Microservices, a generic workflow engine and full event sourcing are rejected for v1.
