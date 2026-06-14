# Agent Guide

## Product

Kalmio is a mobile-first PWA AI assistant for EV trip and charging planning. Claim: "Viaja sin ansiedad de carga."

## Approved Stack

Frontend: React, Vite, TypeScript, TanStack Router, TanStack Query, Tailwind CSS, shadcn/ui, PWA, A2UI renderer.

Backend: Django, Django Ninja, Django ORM, GeoDjango, Postgres/PostGIS, provider-backed routing, authorized charger imports.

## Development Commands

- Frontend: `cd frontend && npm install && npm run dev`.
- Backend: `cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt && python manage.py migrate && python manage.py runserver`.
- Docker: `docker compose up --build`.

## Phase Rules

- Complete Phase 0, Phase 0.5, and Phase 1 before Phase 2.
- Split large features into vertical slices.
- Keep docs current when architecture, A2UI, or design decisions change.
- Keep production docs current when runtime contracts, data imports, routing, A2UI, or design decisions change.

## A2UI Rules

- Only allowlisted components can render as dynamic UI.
- Validate every backend response.
- Unknown frontend blocks render a fallback.
- A broken block cannot crash the whole conversation.

## AI Rules

- Do not invent availability, prices, stations, coordinates, or vehicle state.
- Ask clarifying questions when critical data is missing.
- Fail explicitly when provider-backed routing or authorized charger data is unavailable.
- The agent should interpret natural conversation and follow-ups from the full useful conversation context; do not add regex/intent parsers as the primary way to understand user phrasing.
- Backend code may validate structured arguments, enforce safety constraints, and execute approved tools, but should not become the conversational reasoning layer.

## Design Rules

- Mobile-first, calm, premium, trustworthy.
- Avoid generic AI UI and generic SaaS dashboards.
- Avoid excess cards without hierarchy.
- Use shadcn/ui as technical base only.
- Use Impeccable before important UI screens.
- Maintain consistent spacing, typography, color, states, and microcopy.
- Avoid generic gradients and overloaded layouts.
- Prefer design tokens and Tailwind utilities directly. Add semantic CSS classes only when they encapsulate reused patterns, complex CSS, or behavior that utilities express poorly; avoid creating a parallel design system with one-off semantic classes.

## Security Rules

- Do not install unknown MCPs without approval.
- Do not grant global filesystem access.
- Do not connect MCPs to real or production data.
- Do not store API keys in the repo.
- Do not execute destructive commands without confirmation.
- Do not allow arbitrary UI outside the A2UI catalog.
