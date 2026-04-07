# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- Added Bart's long-lived token to home setup button

## [1.0.27] - 2026-04-07

### Added

- Extended the night price predictor to 8 hours instead of 4

## [1.0.26] - 2026-04-07

### Added

- Fix for the mode 4 fallback setting
- Integration with Home Assistant push notifications

## [1.0.25] - 2026-04-07

### Added

- Moved Enever API token its own config setting

## [1.0.24d] - 2026-03-31

### Added

- Added a price predictor for the first four hours of the next day, based on a linear regression model

## [1.0.24] - 2026-03-31

### Added

- Fix for mode 4 that generates mixed charging/discharging schedules

## [1.0.23b] - 2026-03-30

### Added

- Fix for mode 4 PBapp sign
- Correctly apply battery inverter efficiency when computing PBapp from schedule

## [1.0.23] - 2026-03-30

### Added

- Mode 4 (dynamic schedule) implementation

## [1.0.22b] - 2026-03-26

### Added

- Mode 3 (static schedule) implementation

## [1.0.21] - 2026-01-29

### Added

- Modbus connection to SMA Data Manager

## [1.0.7] - 2025-11-25

### Added

- Implemented smart manual charging
- Added option to configure control loop delay

## [1.0.5] - 2025-11-25

### Added

- Added option to turn on additional debug messages in the log

## [1.0.4] - 2025-11-25

### Added

- Inverter battery charge percentage, voltage and current sensor reading

## [1.0.3] - 2025-11-25

### Added

- Inverter temperature sensor reading
