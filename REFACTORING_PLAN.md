# Refactoring Plan: Gree Climate Component

**Guiding Principles:**

*   **Safety First:** Implement unit tests *before* refactoring to catch regressions.
*   **Incremental Changes:** Break down the refactoring into small, manageable steps.
*   **Always Working:** Each step should result in a functional (though perhaps not fully refactored) component.
*   **Clear Separation:** The primary goal is to separate Home Assistant entity logic from Gree device communication protocol logic.

---

**Phase 0: Preparation & Safety Harness (Unit Tests)**

- [x] **Step 0.1: Set up Testing Framework & Environment.**
    - [x] **Step 0.1.1:** Install Python 3.12. (Stop after this step for review/commit.)
    - [x] **Step 0.1.2:** Install `uv`. (Stop after this step for review/commit.)
    - [x] **Step 0.1.3:** Create Virtual Environment (`.venv`). (Stop after this step for review/commit.)
    - [x] **Step 0.1.4:** Install Test Dependencies (`pytest`, `pytest-asyncio`, `homeassistant`, `pycryptodome`). (Stop after this step for review/commit.)
    - [x] **Step 0.1.5:** Create `tests/` Directory. (Stop after this step for review/commit.)
    - [x] **Step 0.1.6:** Add `pytest.ini`. (Stop after this step for review/commit.)
    - [ ] **Step 0.1.7:** Create/Update `.gitignore`. (Stop after this step for review/commit.)
- [x] **Step 0.2: Create Basic Test File Structure.** (Stop after this step for review/commit.)
    - [x] **Step 0.2.1:** Create initial `tests/test_climate.py`.
    - [x] **Step 0.2.2:** Add global mocks for `socket`, `Crypto`.
    - [x] **Step 0.2.3:** Create basic fixtures (`mock_hass`, `gree_climate_device`).
- [x] **Step 0.2.4: Plan and Stub Test Cases.** (Stop after this step for review/commit.)
    - [x] Define empty test methods in `tests/test_climate.py`.
- [x] **Step 0.2.5: Refactor Tests into Separate Files.** (Stop after this step for review/commit.)
    - [x] Create `tests/conftest.py` and move fixtures, constants, global mocks.
    - [x] Create `tests/test_init.py` and move initialization tests.
    - [x] Create `tests/test_properties.py` and move property tests.
    - [x] Create `tests/test_update.py` and move update tests.
    - [x] Create `tests/test_command.py` and move command tests.
    - [x] Delete original `tests/test_climate.py`.
- [x] **Step 0.3: Implement and Fix `GreeClimate.update` Tests.**
    - [x] **Step 0.3.1: Finalize `test_update_calls_get_values`.**
        - [x] Implement initial logic (mocking, calling update).
        - [x] Add `try...except IndexError` block and logging.
        - [x] Add setup to prevent initial feature check call (`_has_temp_sensor = False`, etc.).
        - [x] Fix `assert_called_once_with` arguments to match actual mock call. 
        - [x] Verify test passes. (Stop after this step for review/commit.)
    - [x] **Step 0.3.2: Finalize `test_update_success_full` (xfail).**
        - [x] Implement test logic.
        - [x] Mark as `xfail` due to known source code issue. (Stop after this step for review/commit.)
        - [x] Verify test is marked `XFAIL` in output. (Stop after this step for review/commit.)
    - [x] **Step 0.3.3: Implement `test_update_timeout`.** (Stop after this step for review/commit.)
    - [x] **Step 0.3.4: Implement `test_update_invalid_response`.** (Stop after this step for review/commit.)
    - [x] **Step 0.3.5: Implement `test_update_sets_availability`.** (Stop after this step for review/commit.)
- [ ] **Step 0.4: Implement and Fix `GreeClimate` Command Method Tests.**
    - [ ] **Step 0.4.1: Fix `mock_hass` fixture for command tests.**
        - [x] Add mock `hass.loop.call_soon_threadsafe` in `conftest.py`. (Stop after this step for review/commit.)
    - [ ] **Step 0.4.2: Finalize `test_async_turn_on`.**
        - [x] Implement initial logic.
        - [x] Verify test passes (after Step 0.4.1 fix). (Stop after this step for review/commit.)
    - [ ] **Step 0.4.3: Finalize `test_async_turn_off`.**
        - [x] Implement initial logic.
        - [x] Verify test passes (after Step 0.4.1 fix). (Stop after this step for review/commit.)
    - [x] **Step 0.4.4: Implement `test_async_set_temperature`.** (Stop after this step for review/commit.)
    - [x] **Step 0.4.5: Implement `test_async_set_hvac_mode`.** (Stop after this step for review/commit.)
    - [ ] **Step 0.4.6: Implement `test_async_set_fan_mode`.** (Stop after this step for review/commit.)
    - [ ] **Step 0.4.7: Implement `test_async_set_swing_mode`.** (Stop after this step for review/commit.)
- [ ] **Step 0.5: Implement and Fix Other Foundational Tests.**
    - [ ] **Step 0.5.1: Finalize `test_properties_before_update`.**
        - [x] Implement initial logic.
        - [x] Correct `hvac_mode` assertion and `HVACMode` import. (Stop after this step for review/commit.)
        - [ ] Verify test passes. (Stop after this step for review/commit.)
    - [ ] **Step 0.5.2: Finalize `test_init_minimal_config`.**
        - [x] Implement initial logic.
        - [ ] Verify test passes. (Stop after this step for review/commit.)
    - [ ] **Step 0.5.3: Finalize `test_init_with_optional_entities`.**
        - [x] Implement initial logic (stub).
        - [ ] Add TODO comment or basic implementation if feasible now. (Stop after this step for review/commit.)

**Phase 1: Introduce the Communication API Class**

- [ ] **Step 1.1: Create `device_api.py`.** (Stop after this step for review/commit.)
- [ ] **Step 1.2: Define `GreeDeviceApi` Class Structure.** (Stop after this step for review/commit.)
- [ ] **Step 1.3: Instantiate `GreeDeviceApi` in `GreeClimate`.** (Stop after this step for review/commit.)

**Phase 2: Incrementally Migrate Communication Logic**

- [ ] **Step 2.1: Migrate Core Sending/Receiving Logic.**
- [ ] **Step 2.2: Migrate Device Binding / Key Exchange.**
- [ ] **Step 2.3: Migrate Status Fetching (`update`).**
- [ ] **Step 2.4: Migrate `set_power` (`turn_on`/`turn_off`).**
- [ ] **Step 2.5: Migrate `set_target_temperature`.**
- [ ] **Step 2.6: Migrate `set_hvac_mode`.**
- [ ] **Step 2.7: Migrate `set_fan_mode`.**
- [ ] **Step 2.8: Migrate `set_swing_mode`.**
- [ ] **Step 2.9: Migrate Optional Feature Controls (Lights, XFan, etc.).**

**Phase 3: Refinement and Cleanup**

- [ ] **Step 3.1: Review `GreeClimate` for Remnants.**
- [ ] **Step 3.2: Refine `GreeDeviceApi` Internals.**
- [ ] **Step 3.3: Add Docstrings.**
- [ ] **Step 3.4: Add Unit Tests for `GreeDeviceApi`.**

**Phase 4: Optional Future Enhancements (Beyond Core Refactor)**

- [ ] **Step 4.1: Add Type Hinting.**
- [ ] **Step 4.2: Improve Configuration Handling.**
- [ ] **Step 4.3: Refactor Constants.** 