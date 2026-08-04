# ADR-006: Keep the Web toolchain compatible with installed Node 22 LTS

Status: accepted on 2026-08-03.

## Context

LiveClip targets Node.js LTS and this development Mac provides native arm64 Node 22.11.0 at `/usr/local/bin`; the default PATH Node 26 is not LTS. Registry metadata checked on 2026-08-03 reports that current Vite 8.2.0 and `@vitejs/plugin-react` 6.0.5 require Node `^20.19.0 || >=22.12.0`. Silently using them would leave `make setup`, Vite and browser tests outside their supported engine on the available LTS installation.

The latest compatible lines checked from the same registry are Vite 6.4.3 (`^18 || ^20 || >=22`) and Vitest 3.2.7 with the same Node family support. React 19.2.8, TanStack Query 5.101.4 and TypeScript 5.9.3 do not require changing the product architecture. MSW is pinned to 2.10.5 because its Node >=18 dependency tree avoids newer Inquirer releases that require Node 22.13.

## Decision

Use exact, locked Vite 6.4.3, plugin-react 4.7.0, Vitest 3.2.7, TypeScript 5.9.3 and MSW 2.10.5 for v1. `make setup`, `make lint` and `make test` explicitly choose `/usr/local/bin` and a project-local npm cache. The install audit currently reports zero known vulnerabilities.

This changes no user capability: the review console remains React/TypeScript/Vite with component and Playwright tests. Re-evaluate the current Vite line after the project Node LTS is at least 22.12; an upgrade must pass the same build, component and browser gates.

## Alternatives

- Upgrade the system Node installation now: rejected because project setup must not mutate system-level tools without separate authority.
- Use the default Node 26: rejected because it violates the requested LTS baseline.
- Ignore engine warnings: rejected because repeatable setup must operate within supported version ranges.
