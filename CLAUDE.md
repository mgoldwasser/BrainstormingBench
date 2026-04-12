# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

BrainstormingBench is an evaluation framework to test the creativity and brainstorming capabilities of AI (per `README.md`).

## Current State

The repository is in its initial scaffolding phase. Aside from `README.md`, no source code, build configuration, dependency manifests, or tests exist yet. When beginning implementation:

- There is no established language, framework, or directory layout — these decisions have not been made and should be confirmed with the user before introducing build systems, lockfiles, or large scaffolding.
- There are no commands to build, lint, or test yet. Update this file with the project's commands once they are established.
- There is no architecture to describe yet. Once the evaluation framework has concrete components (e.g., task/prompt definitions, model-runner interfaces, scoring/judging logic, result aggregation), document the big-picture flow here so future sessions don't have to re-derive it.
