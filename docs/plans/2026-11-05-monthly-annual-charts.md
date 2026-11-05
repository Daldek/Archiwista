# Plan: charts of monthly series and of annual extremes on the station card

Approved: 2026-11-05, the author („ok”); P1 to P4 on `feature/monthly-annual-charts`, P5 (smoke on :8090) after the author's merge. Written on 2026-11-05 at the author's request („Chciałbym, żeby dla danych miesięcznych i rocznych też były wizualizacje. Nie jest to wykonywanie skomplikowanych obliczeń, tylko wyszukanie max i min, więc na potrzeby wizualizacji śmiało może to robić Archiwista. Dane półroczne pomijamy”), with the author's answers of the same day: the annual values come from the half-year characteristics, an incomplete year shows its value with a mark, only the maximum and the minimum, the station card first and the comparison later.

Requirements: SPEC 5.7, 6.7 and 9.2 (`GET /stations/{code}/series`); A-ADR-045 decisions 9 and 11 (the chart of a series; half-year characteristics are markers, never a line, `400 half_year_chart`); SCOPE 1.3 and PRD P17 (Archiwista computes no statistics). DEV-17.2, DEV-17.4.

## Goal

The station card's tab „Wykres” draws, besides the daily series:

- a monthly series (`pl.imgw.hydro_monthly`) as IMGW publishes it: the month's minimum, mean and maximum of H, Q or T;
- the annual maximum and minimum of each hydrological year, found by Archiwista in the half-year characteristics (`pl.imgw.hydro_semiannual`), for display only.

A station that has only half-year characteristics (the case of 152160140 POZNAŃ-MOST ROCHA on :8090 today) shows the annual chart instead of „Stacja nie ma szeregu, który można narysować na wykresie”.

## What exists (2026-11-05, `develop` `b253244`)

- `GET /stations/{code}/series` (`station_chart`, `src/archiwista/api/stations.py:295`; `services/series_chart.py`) reads one series through `SeriesValuesAdapter.read_values`, one point per unit or the least, mean and greatest value of each interval when there are more units than `max_points`, gap bands from the index, the half-year extremes as markers of a daily chart (`extreme_markers`). A half-year series is refused with `400 half_year_chart` (`stations.py:411`, `:719`).
- The web chart (`views/station-chart.js`) offers the station's series but half-year ones (`chartSeries`, line 115), a series selector when there are several (`chart_dataset`) and one or two variables (`chart_variable`).
- Monthly series: the adapter maps `time_unit` `month` (`adapter/obserwator/adapter.py:130`); nothing refuses them, but no test or store has drawn one. Their variables are `<V>_min`, `<V>_mean`, `<V>_max` per month (H, Q, T), so today the card would offer nine separate variables.
- Half-year characteristics (`obserwator-series/1`, read on :8090): one row per hydrological year and `period` (`winter`, `summer`, `annual`); per variable `<V>_min|mean|max` its `_value`, `_flag` (`value`, `missing`), `_start`, `_end` and `_occurrences` (IMGW's repeated rows of one value are already one record: 152160140, 2020 summer Q max 103 m³/s, 29–31 October, 2 occurrences). IMGW publishes for the year only the mean: in all 78 archives of 2000–2025 the period `15` has the extreme code `2` only, so `<V>_min@annual` and `<V>_max@annual` are `missing` everywhere. A half can be absent or `missing`: of the 1,041 stations of 2000–2025, 174 station-years have the Q maximum of one half only (150210080: 2019 winter only, 2020 and 2021 summer only); 152160140 has both halves in every year.
- No meteorological monthly or half-year dataset exists in Obserwator `1ee5457`.

## Decisions

| # | Decision |
|---|---|
| D1 | **Monthly chart.** A series of `time_unit` `month` is drawn per quantity, not per column: the variable selector offers H, Q, T (those with a value), and the chart draws the monthly mean as the line and the band from the monthly minimum to the monthly maximum, all three as IMGW publishes them. When there are more months than `max_points`, an interval's band is the least minimum and the greatest maximum of its months and its line the mean of their means (the simplification the daily chart already makes and says so). „Druga zmienna” keeps working on the quantity. |
| D2 | **Annual extremes.** A new chart resolution „Roczne” for a station with half-year characteristics: per hydrological year and quantity, the maximum is the greater of the winter and summer maxima and the minimum the lesser of the two minima, with the date span and the number of occurrences of the half that holds it (both halves when equal: the union of their spans, the occurrences added). Nothing else is computed: no mean, no other statistic. |
| D3 | **Incomplete year.** A year with one half `missing` or absent shows the value of the other half, marked: a hollow point and the tooltip „niepełny rok: brak półrocza zimowego” (or „letniego”). A year with neither half is a gap band. |
| D4 | **Hydrological years only.** Half-year characteristics have no calendar year (`year_types`, `index/series.py:103`); the annual chart numbers hydrological years and says so next to the year-type switch, which it leaves as it is for the other charts. |
| D5 | **Display only.** The values are found at read time in the chart service and are never stored, indexed, exported, pinned or written into a project; the API marks them derived (`derived: "annual_extremes"` with the rule in its description) and the chart's caption says „roczne maksimum i minimum wyznaczone przez Archiwistę z charakterystyk półrocznych IMGW-PIB”. |
| D6 | **API and CLI.** `GET /stations/{code}/series` gains `resolution`: `unit` (default, unchanged, `half_year_chart` stays) or `annual` (requires a half-year series of the station, else `400 no_annual_source`; `year_type` must be hydrological, else `400 annual_year_type`); its points carry `max` and `min` each with `value`, `start`, `end`, `occurrences`, and `partial` naming the missing half. `archiwista stations series --resolution annual` prints the same. Both answer in the model of the route (AGI-3.2 deviation). |
| D7 | **The card's default.** The tab picks the daily series, else the monthly one, else the annual chart; the series selector lists „Roczne (z charakterystyk półrocznych)” beside the series. The message „Stacja nie ma szeregu…” stays for a station with none of the three. |
| D8 | **Docs.** A new A-ADR-051 amends A-ADR-045 decisions 9 and 11 and the boundary of SCOPE 1.3 / PRD P17: „for display, Archiwista finds the annual maximum and minimum of a hydrological year in the half-year characteristics; it computes no other statistic”. SPEC 5.7, 6.7, 9.2, AGENT_API, USAGE, the guide's slide on stations and CHANGELOG follow. |

Out of scope: the comparison of stations (`station-compare.js`; next step), the timeline, half-year characteristics drawn as their own line, annual values from daily or monthly series, meteorological data.

## Phases

| # | Change | Verified by |
|---|---|---|
| P1 | D2, D3, D5, D6: the service finds the annual extremes; the route and the CLI take `resolution`; refusals `no_annual_source`, `annual_year_type` in the error registry mapping and the message catalog | integration tests on a store of `obserwator.testing` with half-year characteristics: greater/lesser half, equal halves (spans joined, occurrences added), one half missing (partial), none (gap), a refused calendar year, CLI equal to HTTP |
| P2 | D1: monthly series per quantity with its band; downsampling of the band | integration test on a monthly store of `obserwator.testing`; e2e: the band and the line of a monthly chart |
| P3 | D4, D7: the web chart's „Roczne”, its hollow partial points and tooltips, the card's default | e2e (Chromium): a station with half-year characteristics only opens on the annual chart; a partial year's tooltip |
| P4 | D8: A-ADR-051, SPEC, SCOPE, PRD, AGENT_API, USAGE, guide, CHANGELOG, PROGRESS | `scripts/gate.sh` |
| P5 | Smoke on :8090 after the author's merge: 152160140 annual chart 2000–2025 (2024: Q max 223 m³/s on 2024-03-02, winter; Q min 32.7 m³/s on 18–19 August, summer, 2 occurrences), 150210080 with partial years 2019 to 2021, and a monthly chart after `store sync` of `pl.imgw.hydro_monthly` | the card in a browser, `archiwista stations series 152160140 --resolution annual` |

## Risks

- **Dates IMGW gives without a day.** The winter 2020 Q maximum of 152160140 is published as „2020-03” with no day; Obserwator stores it as 2020-03-01. Archiwista cannot tell such a date from a real first of the month, so the tooltip would show a day IMGW never gave. A `request` to Obserwator (DEV-17.5) for the precision of an occurrence date; until then the tooltip shows the date as stored.
- **Monthly and half-year extremes of IMGW may be instantaneous**, so they can exceed the daily series' extremes; the chart says where each value comes from and mixes no sources.
- The amendment of P17 is a change of the product's boundary: D8 limits it to finding the two extremes, so it does not open the way to statistics that belong to Hydrolog.

## Errata (2026-11-05, during P1 to P3)

1. The source interface grows (D1, D2): `SeriesValuesAdapter.statistics_of(dataset)` names the minimum, mean and maximum variables of a dataset of months or half-years, from the producer's registry; `SeriesValues.occurrences` carries the count of an extreme; `Statistic` is exported by `archiwista.sources`. A plugin implementing `SeriesValuesAdapter` adds `statistics_of`.
2. `variable` may be left out of `resolution=annual` only (each variable with a value), so P5's command works as written; a chart of units without it stays `400 validation_error`.
3. The card's answer names its charts (`StationCard.charts`: dataset, time unit, resolution and variables), so the web never reads a producer's variable names.
4. An annual extreme also names the half or halves that hold it (`halves`).
5. The gaps of an annual chart are the years in the union of the gap runs of the labels of `<V>_max` and `<V>_min` of both halves, less the years with a value.
6. Without `dataset`, a chart of units prefers the daily series to the monthly one, so `variable=H` stays unambiguous once monthly data are synced.

## Results

P1 to P4 built on 2026-11-05 on `feature/monthly-annual-charts` (stacked on `fix/distinct-notices`); A-ADR-051.

- P1, P2: `services/series_chart.py` (`annual_chart`, `annual_points`, `annual_gaps`, the monthly band in `chart_values`), `api/stations.py` and `api/models_stations.py` (`resolution`, `derived`, `charts`), `commands/stations.py`, the adapter's `statistics_of`. `tests/integration/test_station_statistics_api.py` over a store of IMGW-PIB's layout built by Obserwator's own `sync_store` (`tests/fixtures/obserwator_statistics.py`; `obserwator.testing` holds one station's 2024 with equal halves only).
- P3: `views/station-chart.js` (the chip „Roczne (z charakterystyk półrocznych)”, the maximum solid and the minimum dashed, hollow partial points, the note „Wykres roczny: zawsze lata hydrologiczne”, the monthly band), `views/station.js`. `tests/e2e/test_station_chart.py`: the monthly band, a station with half-year characteristics only opening on the annual chart, a partial year's tooltip (Chromium and Firefox, 6 passed).
- A local smoke on a copy of the test server's Obserwator store: 152160140 POZNAŃ-MOST ROCHA draws H, Q and T 2000–2025 as annual maxima and minima.
- P4: A-ADR-051, SPEC 1.3, 5.7, 6.7, 9.2 and P17, SCOPE, PRD F11.3, AGENT_API, USAGE, ARCHITECTURE, CHANGELOG. The guide (`/instrukcja`) has no slide on stations yet, so D8's guide change has nothing to amend.
