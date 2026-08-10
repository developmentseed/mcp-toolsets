"""The one DuckDB connection this toolset ever opens, and its security model.

Read this before touching ``tools.py``. The connection is built once, at
import time, in :func:`_build_connection`: extensions are installed, the
curated views are created, and then the connection is locked down before any
caller-supplied SQL ever runs against it. ``query``/``chart`` in ``tools.py``
only ever get a ``cursor()`` off the already-locked-down :data:`CON`.

SECURITY MODEL — four layers, in decreasing order of how much they actually
protect this connection from a hostile ``SELECT``:

1. **The deployment has no local secrets reachable, full stop.** This is the
   PRIMARY control, and it lives outside this file entirely: nothing in
   Python can compensate for a `.env`, a mounted Secret, or an ambient AWS
   credential sitting in this container's filesystem or environment. This
   toolset's ``pyproject.toml`` declares no ``CREDENTIAL_HEADERS``, needs no
   secrets in ``toolset.yaml``, and the shared ``Dockerfile`` ships a bare
   ``python:3.12-slim-bookworm`` runtime image with nothing baked in beyond
   the venv. If that ever changes for this toolset specifically, this
   connection's threat model changes with it — grep for "PRIMARY control"
   before adding any credential to this toolset's deployment.

2. **DuckDB is configured so its own filesystem access can't reach local
   disk while ``https://``/``s3://`` reads keep working.** DuckDB's
   documented, all-or-nothing knob (``SET enable_external_access = false``)
   was tried first and rejected: it disables ``read_csv``/``read_parquet``/
   ``read_json`` reading from *any* external source, remote included — see
   https://duckdb.org/docs/stable/operations_manual/securing_duckdb/overview.
   ``SET disabled_filesystems = 'LocalFileSystem'`` is DuckDB's documented,
   finer-grained alternative (it's literally their own worked example for
   blocking ``read_csv('/etc/passwd', ...)``), and empirically it *does*
   deliver local-blocked/remote-allowed — but only once the connection's
   remote filesystem path has been exercised at least once beforehand. Prior
   to that first remote read, DuckDB's own httpfs/spatial code paths still
   touch local disk internally (e.g. to resolve/cache a filesystem handle),
   so a `disabled_filesystems` set on a "cold" connection blocks the first
   remote read too — a real DuckDB limitation, tracked upstream as
   https://github.com/duckdb/duckdb/issues/15734 for the plain-httpfs case,
   and reproduced here for ``spatial``'s ``ST_Read`` as well. Verified
   directly against this toolset's pinned DuckDB version (see the
   ``dependencies`` pin in ``pyproject.toml``): one warmup read of *any*
   remote URL, of *any* kind (plain https, s3://, or ``ST_Read``), before
   locking down, is sufficient — every remote kind then keeps working for
   arbitrary new URLs afterwards, while local paths stay blocked. That is
   exactly what ``_warm_up_remote_filesystem`` below does, and it runs
   before ``_register_views`` for good measure (creating each view already
   touches its remote source once, but the explicit warmup makes the
   ordering requirement self-documenting instead of incidental). This is a
   real, verified technical control, not a fig leaf — but it rests on an
   *undocumented* DuckDB behavior (one-time-touch-then-cached), which is one
   more reason layer 1 is the control this toolset actually depends on, not
   this one.
3. ``SET lock_configuration = true`` is set last, after every setting above,
   so no runtime SQL — even something that slips past ``security.py``'s
   statement-shape filter — can loosen any of it. ``SET allow_community_extensions
   = false`` runs just before it, so the ``stac`` community extension can be
   loaded once here but never again from caller SQL.
4. ``security.validate_select_only`` (defense-in-depth, checked before any
   caller SQL reaches this connection): single-statement, ``SELECT``/``WITH``
   only, plus a small denylist for introspection functions
   (``duckdb_secrets()`` etc.) that are otherwise valid inside a plain
   ``SELECT``. This does **not** stop ``read_text('/etc/passwd')`` — that
   starts with ``SELECT`` and is one statement, so it sails through this
   check. It's stopped by layer 2 (and, ultimately, guaranteed by layer 1).

Extensions are pinned by name (``httpfs``, ``spatial``, and the community
``stac`` extension) — nothing under ``duckdb-analyst`` ever calls
``INSTALL``/``LOAD`` again after connection setup, and layer 3 makes sure
caller SQL couldn't anyway. ``httpfs``/``spatial`` are core DuckDB
extensions, so their versions are pinned transitively by this toolset's
pinned ``duckdb`` dependency. The community ``stac`` extension
(https://github.com/ahuarte47/duckdb-stac) has no independent version pin
available through ``INSTALL ... FROM community`` — it always resolves to
the latest build published for the installed DuckDB version. That's an
accepted, small supply-chain trust boundary (single maintainer, MIT
licensed, reviewed before adding here), not something this file can pin
away.
"""

from typing import NotRequired, TypedDict

import duckdb

#: Overture release to read. Deliberately pinned, not globbed
#: (``release/*/...``): the public bucket keeps more than one release
#: available at a time, so a wildcard here would silently union
#: possibly-incompatible releases into one view. Bump this string
#: periodically — see https://docs.overturemaps.org/getting-data/duckdb/ for
#: the current release list.
OVERTURE_RELEASE = "2026-07-22.0"
_OVERTURE_BUCKET = "s3://overturemaps-us-west-2"

# Official Natural Earth vector data, unzipped, served directly over plain
# https by the project's own GitHub organization
# (https://github.com/nvkelso/natural-earth-vector — nvkelso is a Natural
# Earth maintainer; this is the canonical vector-data repo, not a random
# mirror). Deliberately NOT the zipped shapefiles naturalearthdata.com links
# to: this DuckDB build's `spatial` extension has no working GDAL vsicurl
# support (verified: `/vsicurl/...` and `/vsizip/vsicurl/...` both fail to
# open, on or off the lockdown below), but `ST_Read` handles a plain
# `https://` URL itself via DuckDB's own httpfs filesystem — the same code
# path `read_parquet`/`read_csv` use, and the one the warmup below exercises.
_NATURAL_EARTH_COUNTRIES_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_110m_admin_0_countries.geojson"
)
_NATURAL_EARTH_PLACES_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_110m_populated_places.geojson"
)

#: Microsoft Planetary Computer's public, no-auth STAC API — same catalog
#: `stac-explorer` already uses (see its `STAC_ROOT`). `STAC_Search`'s `url`
#: argument is this endpoint's Item Search route.
PC_STAC_SEARCH_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"

#: Conservative resource caps for a shared, always-on connection. Sized
#: against this toolset's `toolset.yaml` pod memory limit, with headroom for
#: Python/uvicorn overhead alongside DuckDB itself.
_MEMORY_LIMIT = "700MB"
_THREADS = 2


class ColumnInfo(TypedDict):
    """One column of a curated source, as advertised by ``list_sources``."""

    name: str
    type: str
    description: NotRequired[str]
    #: Vega-Lite encoding channels this column tends to work well as.
    good_for: NotRequired[list[str]]


class SourceInfo(TypedDict):
    """One pre-registered source, as advertised by ``list_sources``."""

    name: str
    kind: str  # "view" (curated, fixed schema) | "table_function" (SQL fn)
    description: str
    example_sql: str
    columns: NotRequired[list[ColumnInfo]]


def _build_connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute(f"SET memory_limit = '{_MEMORY_LIMIT}'")
    con.execute(f"SET threads = {_THREADS}")

    # Pinned extensions only — see the module docstring, layer "Extensions".
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")
    con.execute("INSTALL stac FROM community")
    con.execute("LOAD stac")

    # Overture's bucket is genuinely anonymous/unsigned — no CREATE SECRET,
    # no credentials, just the region (verified directly against the live
    # bucket; this is also the pattern Overture's own docs recommend).
    con.execute("SET s3_region = 'us-west-2'")

    _warm_up_remote_filesystem(con)
    _register_views(con)

    # Lock down. See the module docstring, layer "DuckDB is configured...",
    # for why this order (and the warmup above) is load-bearing.
    con.execute("SET disabled_filesystems = 'LocalFileSystem'")
    con.execute("SET allow_community_extensions = false")
    con.execute("SET lock_configuration = true")
    return con


def _warm_up_remote_filesystem(con: duckdb.DuckDBPyConnection) -> None:
    """Touch DuckDB's remote filesystem path once before locking local disk.

    See the module docstring for why this is necessary and what it's based
    on. Any tiny, reliably-reachable remote read does the job; this one is
    deliberately unrelated to the views below so the requirement doesn't
    look like an accident of registration order.
    """
    con.execute(
        "SELECT 1 FROM read_parquet('https://duckdb.org/data/holdings.parquet') LIMIT 1"
    )


def _register_views(con: duckdb.DuckDBPyConnection) -> None:
    # Each view's SQL is built as a plain string first and executed on its
    # own line, rather than inlining `con.execute(f"""...""")` directly, so
    # the linter-suppression comment below has an unambiguous line to
    # attach to instead of landing inside the SQL string itself. The
    # underlying ruff finding ("possible SQL injection") is a false
    # positive: the only interpolated values here are module constants (a
    # pinned release date, hardcoded dataset URLs) — never caller input,
    # which is what actually makes string-built SQL dangerous.
    divisions_path = (
        f"{_OVERTURE_BUCKET}/release/{OVERTURE_RELEASE}/"
        "theme=divisions/type=division_area/*"
    )
    divisions_sql = f"""
        CREATE VIEW overture_divisions AS
        SELECT
            id,
            subtype,
            class,
            country,
            region,
            admin_level,
            names."primary" AS primary_name,
            is_land,
            is_territorial,
            bbox.xmin AS bbox_xmin,
            bbox.ymin AS bbox_ymin,
            bbox.xmax AS bbox_xmax,
            bbox.ymax AS bbox_ymax,
            geometry
        FROM read_parquet('{divisions_path}')
    """  # noqa: S608
    con.execute(divisions_sql)

    places_path = (
        f"{_OVERTURE_BUCKET}/release/{OVERTURE_RELEASE}/theme=places/type=place/*"
    )
    places_sql = f"""
        CREATE VIEW overture_places AS
        SELECT
            id,
            names."primary" AS primary_name,
            categories."primary" AS category,
            confidence,
            operating_status,
            basic_category,
            brand.names."primary" AS brand_name,
            addresses[1].country AS country,
            addresses[1].region AS region,
            addresses[1].locality AS locality,
            bbox.xmin AS bbox_xmin,
            bbox.ymin AS bbox_ymin,
            bbox.xmax AS bbox_xmax,
            bbox.ymax AS bbox_ymax,
            geometry
        FROM read_parquet('{places_path}')
    """  # noqa: S608
    con.execute(places_sql)

    countries_sql = f"""
        CREATE VIEW natural_earth_countries AS
        SELECT
            "NAME" AS name,
            "ADMIN" AS admin_name,
            "ISO_A2" AS iso_a2,
            "ISO_A3" AS iso_a3,
            "CONTINENT" AS continent,
            "SUBREGION" AS subregion,
            "POP_EST" AS population_estimate,
            "GDP_MD" AS gdp_million_usd,
            "INCOME_GRP" AS income_group,
            geom AS geometry
        FROM ST_Read('{_NATURAL_EARTH_COUNTRIES_URL}')
    """  # noqa: S608
    con.execute(countries_sql)

    places_ne_sql = f"""
        CREATE VIEW natural_earth_places AS
        SELECT
            "NAME" AS name,
            "ADM0NAME" AS country_name,
            "ISO_A2" AS iso_a2,
            "LATITUDE" AS latitude,
            "LONGITUDE" AS longitude,
            "POP_MAX" AS population_max,
            "TIMEZONE" AS timezone,
            geom AS geometry
        FROM ST_Read('{_NATURAL_EARTH_PLACES_URL}')
    """  # noqa: S608
    con.execute(places_ne_sql)


# Hand-authored notes on top of each view's real, live-introspected schema
# (see _build_sources): the things a schema dump can't tell an LLM, like
# which columns make good chart channels. A column with no entry here still
# appears in list_sources with just its name/type.
_COLUMN_NOTES: dict[str, dict[str, ColumnInfo]] = {
    "overture_divisions": {
        "subtype": {
            "name": "subtype",
            "type": "",
            "description": "country / region / county / locality / etc.",
            "good_for": ["x", "color"],
        },
        "country": {
            "name": "country",
            "type": "",
            "description": "ISO 3166-1 alpha-2 country code.",
            "good_for": ["x", "color"],
        },
        "region": {
            "name": "region",
            "type": "",
            "description": "ISO 3166-2 principal-subdivision code.",
            "good_for": ["x", "color"],
        },
        "admin_level": {
            "name": "admin_level",
            "type": "",
            "description": "Depth in the administrative hierarchy (0=country).",
            "good_for": ["x", "color"],
        },
        "primary_name": {
            "name": "primary_name",
            "type": "",
            "description": "The division's primary display name.",
            "good_for": ["x", "color"],
        },
        "geometry": {
            "name": "geometry",
            "type": "",
            "description": (
                "Polygon/MultiPolygon boundary. Not chart data as-is — wrap "
                "with ST_AsText(geometry) or ST_AsGeoJSON(geometry) if you "
                "need it in a query/chart result."
            ),
        },
    },
    "overture_places": {
        "category": {
            "name": "category",
            "type": "",
            "description": "Primary Overture place-category taxonomy value.",
            "good_for": ["x", "color"],
        },
        "confidence": {
            "name": "confidence",
            "type": "",
            "description": "Model confidence the place exists, 0-1.",
            "good_for": ["y", "color"],
        },
        "country": {
            "name": "country",
            "type": "",
            "description": "Country code of the place's first listed address.",
            "good_for": ["x", "color"],
        },
        "operating_status": {
            "name": "operating_status",
            "type": "",
            "description": "open / temporarily_closed / permanently_closed.",
            "good_for": ["color"],
        },
        "geometry": {
            "name": "geometry",
            "type": "",
            "description": (
                "Point location. Wrap with ST_X(geometry)/ST_Y(geometry) "
                "for plain lon/lat numbers usable as x/y chart channels."
            ),
        },
    },
    "natural_earth_countries": {
        "name": {
            "name": "name",
            "type": "",
            "description": "Country name.",
            "good_for": ["x", "color"],
        },
        "continent": {
            "name": "continent",
            "type": "",
            "good_for": ["x", "color"],
        },
        "population_estimate": {
            "name": "population_estimate",
            "type": "",
            "good_for": ["y", "color"],
        },
        "gdp_million_usd": {
            "name": "gdp_million_usd",
            "type": "",
            "description": "GDP estimate, millions of USD.",
            "good_for": ["y", "color"],
        },
        "income_group": {
            "name": "income_group",
            "type": "",
            "good_for": ["x", "color"],
        },
    },
    "natural_earth_places": {
        "name": {
            "name": "name",
            "type": "",
            "description": "City/place name.",
            "good_for": ["color"],
        },
        "latitude": {"name": "latitude", "type": "", "good_for": ["y"]},
        "longitude": {"name": "longitude", "type": "", "good_for": ["x"]},
        "population_max": {
            "name": "population_max",
            "type": "",
            "description": "High estimate of the place's population.",
            "good_for": ["y", "color"],
        },
    },
}

_VIEW_DESCRIPTIONS = {
    "overture_divisions": (
        "Overture Maps administrative divisions (countries, regions, "
        f"counties, ...), release {OVERTURE_RELEASE}, polygons. Good for "
        "breakdowns by country/region/admin_level."
    ),
    "overture_places": (
        "Overture Maps points of interest (POIs) — businesses, landmarks, "
        f"etc., release {OVERTURE_RELEASE}, points. Good for category/"
        "confidence/operating-status breakdowns; global scale (billions of "
        "rows across all files), so always filter or LIMIT."
    ),
    "natural_earth_countries": (
        "Natural Earth 1:110m country polygons with basic demographic/"
        "economic attributes — a lightweight companion to overture_divisions "
        "when you just need country-level name/population/GDP, not a full "
        "administrative hierarchy."
    ),
    "natural_earth_places": (
        "Natural Earth 1:110m populated places (major world cities) as "
        "points with lat/lon and population — a small, fast dataset good "
        "for quick geographic scatter charts."
    ),
}

_EXAMPLE_SQL = {
    "overture_divisions": (
        "SELECT primary_name, country, admin_level FROM overture_divisions "
        "WHERE subtype = 'country' LIMIT 20"
    ),
    "overture_places": (
        "SELECT category, count(*) AS n FROM overture_places "
        "WHERE country = 'US' GROUP BY category ORDER BY n DESC LIMIT 20"
    ),
    "natural_earth_countries": (
        "SELECT name, continent, population_estimate FROM "
        "natural_earth_countries ORDER BY population_estimate DESC LIMIT 20"
    ),
    "natural_earth_places": (
        "SELECT name, longitude, latitude, population_max FROM "
        "natural_earth_places ORDER BY population_max DESC LIMIT 50"
    ),
}


def _describe_view(con: duckdb.DuckDBPyConnection, view: str) -> list[ColumnInfo]:
    """Live column name/type for a view, merged with any curated notes.

    Reads the real, already-registered view's schema rather than
    hand-listing columns, so this catalog can't drift from what the views
    actually return.
    """
    notes = _COLUMN_NOTES.get(view, {})
    columns: list[ColumnInfo] = []
    for name, duck_type, *_ in con.execute(f"DESCRIBE {view}").fetchall():
        note = notes.get(name, ColumnInfo(name=name, type=""))
        columns.append(ColumnInfo(**{**note, "name": name, "type": str(duck_type)}))
    return columns


def _build_sources(con: duckdb.DuckDBPyConnection) -> list[SourceInfo]:
    sources = [
        SourceInfo(
            name=view,
            kind="view",
            description=_VIEW_DESCRIPTIONS[view],
            example_sql=_EXAMPLE_SQL[view],
            columns=_describe_view(con, view),
        )
        for view in (
            "overture_divisions",
            "overture_places",
            "natural_earth_countries",
            "natural_earth_places",
        )
    ]
    # A hand-written example, not SQL this module ever executes — it's
    # display-only text for list_sources, so ruff's S608 heuristic (which
    # can't tell "this is documentation" from "this runs") is a false
    # positive here.
    stac_example_sql = (
        'SELECT collection, id, datetime, "eo:cloud_cover" '  # noqa: S608
        f"FROM STAC_Search('{PC_STAC_SEARCH_URL}', "
        "collections := ['sentinel-2-l2a'], "
        "bbox := [-122.5, 47.5, -122.0, 47.8], "
        "datetime := '2024-06-01/2024-06-30', max_items := 20)"
    )
    sources.append(
        SourceInfo(
            name="STAC_Search",
            kind="table_function",
            description=(
                "SQL table function (from the `stac` DuckDB extension) that "
                "searches any STAC API's Item Search endpoint. Pointed here "
                "at Microsoft Planetary Computer's public, no-auth catalog "
                f"({PC_STAC_SEARCH_URL}); pass a different `url` for another "
                "STAC API. Common result columns: collection, id, datetime, "
                "bbox, geometry, plus collection-specific properties (e.g. "
                '"eo:cloud_cover") — these vary by collection, so run '
                "`DESCRIBE` on a search first if unsure."
            ),
            example_sql=stac_example_sql,
        )
    )
    return sources


CON = _build_connection()
SOURCES = _build_sources(CON)
