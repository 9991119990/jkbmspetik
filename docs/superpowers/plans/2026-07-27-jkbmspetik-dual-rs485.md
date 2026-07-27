# JKBMS Petik Dual RS485 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a new Home Assistant add-on project that reads two JK BMS units over two RS485 adapters and publishes isolated MQTT entities for each.

**Architecture:** Reuse the existing serial decoder, but replace the single fixed MQTT namespace with per-BMS `topic_prefix` namespaces. The add-on reads each configured BMS serially and handles each BMS failure independently.

**Tech Stack:** Python 3, Home Assistant add-on config schema, raw MQTT v3.1.1 socket publisher, unittest.

---

### Task 1: Project Identity

**Files:**
- Modify: `config.yaml`
- Modify: `README.md`

- [ ] Rename the add-on metadata to `JKBMS Petik RS485 MQTT`.
- [ ] Set slug to `jkbmspetik`.
- [ ] Add a `bms` list to options/schema.
- [ ] Document dual-BMS setup with `/dev/serial/by-path/`.

### Task 2: MQTT Namespace Tests

**Files:**
- Modify: `test_jk_bms_mqtt.py`

- [ ] Add a failing test that a BMS with `topic_prefix=jk_24v300ah` publishes to `jk_24v300ah/state` and `jk_24v300ah/availability`.
- [ ] Add a failing test that two BMS configs publish to independent topics and one failure does not stop the other.

### Task 3: Runtime Implementation

**Files:**
- Modify: `jk_bms_mqtt.py`
- Modify: `run.sh`

- [ ] Add per-BMS config parsing.
- [ ] Add per-prefix discovery IDs, state topics, availability topics, and device identifiers.
- [ ] Add a polling loop over all configured BMS entries.
- [ ] Keep backward-compatible single-port CLI behavior for tests and manual one-shot runs.

### Task 4: Verification and Publish

**Files:**
- Verify: all project files

- [ ] Run `python3 -m unittest test_jk_bms_mqtt.py`.
- [ ] Initialize a new git repo in `jkbmspetik`.
- [ ] Commit the new project.
- [ ] Create/push GitHub repo `jkbmspetik`.
